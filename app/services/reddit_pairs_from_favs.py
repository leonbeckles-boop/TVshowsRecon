# app/services/reddit_pairs_from_favs.py
import os
import re
import asyncio
import logging
from typing import List, Tuple, Dict, Any, Optional, Set

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

# Reuse your resolver
from app.services.title_to_tmdb import lookup_tmdb_id

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)
log = logging.getLogger(__name__)

# --- DB bootstrap
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://tvuser:devpass1@db:5432/tvrecs")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# --- Config
SUBREDDIT = os.getenv("REDDIT_REFRESH_SUBS", "televisionsuggestions")
SEARCH_SORT = os.getenv("REDDIT_SEARCH_SORT", "top")              # relevance|top|new|comments
SEARCH_TIMESPAN = os.getenv("REDDIT_SEARCH_T", "year")            # hour|day|week|month|year|all
THREADS_PER_FAVORITE = int(os.getenv("REDDIT_THREADS_PER_FAV", "25"))
SLOWDOWN_SEC = float(os.getenv("REDDIT_SLOWDOWN_SEC", "1.0"))
USER_AGENT = os.getenv("REDDIT_USER_AGENT", "tvrecs/0.1 by yourapp")
USER_ID = int(os.getenv("USER_ID", "1"))

# --- Simple title extractor (quotes + Title Case sequences)
TITLE_IN_QUOTES = re.compile(r"[“\"']([^“\"']{2,})[”\"']")
CAP_SEQ = re.compile(r"\b([A-Z][A-Za-z0-9&'’\-]*(?:\s+[A-Z][A-Za-z0-9&'’\-]*){0,5})\b")

# Single-word whitelist (common legit show names that would otherwise be ignored)
WHITELIST_SINGLE = {"Lost", "Dark", "From", "Dexter", "Barry", "Servant", "Atlanta", "Severance"}

# Obvious junk / stop phrases we don't want as titles
STOP_WORDS = {
    "I", "We", "You", "It", "They", "He", "She", "Some", "Any", "Shows", "Series",
    "Recommendation", "Recommendations", "Character", "Characters", "Season", "Episode",
    "TV", "Show", "Best", "Worst", "Help", "Thanks", "Please"
}


def extract_titles(text: str) -> List[str]:
    """Best-effort, fast heuristic to pull likely show names from free text."""
    if not text:
        return []

    candidates: Set[str] = set()

    # 1) Things in quotes
    for m in TITLE_IN_QUOTES.finditer(text):
        t = m.group(1).strip()
        if 2 <= len(t) <= 70:
            candidates.add(t)

    # 2) Capitalized sequences (up to 6 tokens)
    for m in CAP_SEQ.finditer(text):
        t = m.group(1).strip()
        if len(t) < 2 or len(t) > 70:
            continue
        # reject overly generic single words
        if " " not in t and t not in WHITELIST_SINGLE:
            continue
        # prune obvious generic phrases
        parts = set(t.split())
        if parts & STOP_WORDS:
            # allow if whitelisted
            if t not in WHITELIST_SINGLE:
                continue
        candidates.add(t)

    # 3) light cleanup
    cleaned = []
    for c in candidates:
        c = re.sub(r"\s+", " ", c).strip()
        c = re.sub(r"[.,!?;:]+$", "", c)
        if 2 <= len(c) <= 70:
            cleaned.append(c)

    # de-dup with casefold key
    seen: Set[str] = set()
    out: List[str] = []
    for t in cleaned:
        k = t.casefold()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


async def fetch_json(url: str) -> Optional[Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=25.0, headers=headers) as client:
        r = await client.get(url)
        if r.status_code != 200:
            log.debug("HTTP %s for %s", r.status_code, url)
            return None
        return r.json()


async def reddit_search_threads(query: str, limit: int) -> List[Dict[str, Any]]:
    """
    Use Reddit public search JSON to find threads in the target sub that mention the query (favorite title).
    """
    q = httpx.QueryParams(
        {
            "q": f'"{query}"',
            "restrict_sr": "1",
            "sort": SEARCH_SORT,
            "t": SEARCH_TIMESPAN,
            "limit": str(limit),
            "include_over_18": "on",
            "type": "link",
        }
    )
    url = f"https://www.reddit.com/r/{SUBREDDIT}/search.json?{q}"
    data = await fetch_json(url)
    if not data:
        return []
    children = data.get("data", {}).get("children", [])
    return [c.get("data", {}) for c in children if c.get("data")]


async def fetch_comments(permalink: str) -> Optional[List[Dict[str, Any]]]:
    url = f"https://www.reddit.com{permalink}.json?limit=500"
    data = await fetch_json(url)
    if not data or not isinstance(data, list) or len(data) < 2:
        return None
    # comments listing at index 1
    return data[1].get("data", {}).get("children", [])


def top_level_comments(tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for node in tree:
        kind = node.get("kind")
        data = node.get("data", {})
        if kind == "t1":  # comment
            out.append(data)
    return out


def resolve_titles_to_ids(titles: List[str]) -> List[int]:
    ids: List[int] = []
    for t in titles:
        tid = lookup_tmdb_id(t)
        if tid:
            ids.append(int(tid))
    return ids


async def get_user_favorites(session: AsyncSession, user_id: int) -> List[int]:
    """
    Fetch TMDB IDs from your favorites table.
    Try common schemas: user_favorites(tmdb_id), favorites(tmdb_id), user_shows(favorite=1) joining shows.external_id.
    """
    # Attempt 1: user_favorites(user_id, tmdb_id)
    res = await session.execute(
        text("SELECT tmdb_id FROM user_favorites WHERE user_id = :uid"),
        {"uid": user_id},
    )
    rows = res.fetchall()
    if rows:
        return [int(r[0]) for r in rows if r[0] is not None]

    # Attempt 2: favorites(user_id, tmdb_id)
    res = await session.execute(
        text("SELECT tmdb_id FROM favorites WHERE user_id = :uid"),
        {"uid": user_id},
    )
    rows = res.fetchall()
    if rows:
        return [int(r[0]) for r in rows if r[0] is not None]

    # Attempt 3: user_shows(user_id, show_id, favorite bool) + shows.external_id numeric TMDB
    res = await session.execute(
        text(
            """
            SELECT CAST(s.external_id AS BIGINT) AS tmdb_id
            FROM user_shows us
            JOIN shows s ON s.show_id = us.show_id
            WHERE us.user_id = :uid AND COALESCE(us.favorite, TRUE) = TRUE
              AND s.external_id ~ '^[0-9]+$'
            """
        ),
        {"uid": user_id},
    )
    rows = res.fetchall()
    return [int(r[0]) for r in rows if r[0] is not None]


async def lookup_title_for_tmdb(session: AsyncSession, tmdb_id: int) -> Optional[str]:
    # Try shows.external_id==tmdb_id for a title
    res = await session.execute(
        text(
            """
            SELECT title
            FROM shows
            WHERE external_id = :tid
            LIMIT 1
            """
        ),
        {"tid": str(tmdb_id)},
    )
    row = res.first()
    if row and row[0]:
        return row[0]
    # Fallback: let resolver search by TMDB ID (not ideal; you may have a dedicated cache/service)
    return None


async def upsert_pairs(
    session: AsyncSession,
    src_tmdb: int,
    dst_tmdbs: List[int],
    subreddit: str,
):
    if not dst_tmdbs:
        return
    # Ensure canonical (a<b) and no self-pairs
    pairs: List[Tuple[int, int]] = []
    for d in dst_tmdbs:
        if d == src_tmdb:
            continue
        a, b = (src_tmdb, d) if src_tmdb < d else (d, src_tmdb)
        pairs.append((a, b))

    # Upsert
    # Requires reddit_pairs table (as created earlier)
    sql = text(
        """
        INSERT INTO reddit_pairs (tmdb_id_a, tmdb_id_b, pair_count, pair_weight, subreddits, updated_at)
        VALUES (:a, :b, 1, 1.0, ARRAY[:sub], now())
        ON CONFLICT (tmdb_id_a, tmdb_id_b)
        DO UPDATE SET
            pair_count = reddit_pairs.pair_count + 1,
            pair_weight = reddit_pairs.pair_weight + 1.0,
            subreddits = (
                SELECT CASE WHEN :sub = ANY(reddit_pairs.subreddits)
                            THEN reddit_pairs.subreddits
                            ELSE array_append(reddit_pairs.subreddits, :sub)
                       END
            ),
            updated_at = now()
        """
    )
    for a, b in pairs:
        await session.execute(sql, {"a": a, "b": b, "sub": subreddit})
    await session.commit()


async def mine_for_favorite(session: AsyncSession, fav_tmdb: int) -> int:
    title = await lookup_title_for_tmdb(session, fav_tmdb)
    if not title:
        # If we don't have a local title, try TMDB name via lookup (cheap fallback)
        # This uses search by ID poorly; better to have a tmdb_details cache.
        title = None

    if not title:
        log.info("[seed %s] skipping: no local title", fav_tmdb)
        return 0

    log.info("[seed %s] searching threads mentioning: %r", fav_tmdb, title)
    threads = await reddit_search_threads(title, THREADS_PER_FAVORITE)
    if not threads:
        log.info("[seed %s] no threads found", fav_tmdb)
        return 0

    found_total = 0
    for th in threads:
        permalink = th.get("permalink")
        if not permalink:
            continue
        await asyncio.sleep(SLOWDOWN_SEC)
        tree = await fetch_comments(permalink)
        if not tree:
            continue
        comment_texts = []
        for c in top_level_comments(tree):
            body = c.get("body", "") or ""
            if body:
                comment_texts.append(body)

        # Extract and resolve in batch
        all_titles: Set[str] = set()
        for txt in comment_texts:
            all_titles.update(extract_titles(txt))

        # Avoid the seed title if it appears
        if title in all_titles:
            all_titles.discard(title)

        # Resolve
        ids = resolve_titles_to_ids(list(all_titles))
        if ids:
            found_total += len(ids)
            await upsert_pairs(session, fav_tmdb, ids, SUBREDDIT)

    log.info("[seed %s] total suggestions stored: %d", fav_tmdb, found_total)
    return found_total


async def main():
    async with Session() as session:
        favs = await get_user_favorites(session, USER_ID)
        if not favs:
            log.warning("No favorites found for user_id=%s", USER_ID)
            return
        log.info("Mining pairs for %d favorites...", len(favs))
        total = 0
        for f in favs:
            total += await mine_for_favorite(session, f)
        log.info("Done. Saved suggestions: %d", total)


if __name__ == "__main__":
    asyncio.run(main())

