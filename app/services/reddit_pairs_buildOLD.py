
"""
Reddit pairs builder (favorites-driven, OAuth-based search)

- Pulls the user's favorites from Postgres (user_favorites)
- For each favorite, fetch TMDB details to get a good canonical title
- Uses Reddit OAuth search on r/televisionsuggestions to find relevant threads
- Fetches each thread's comments (OAuth) and extracts show titles from OP + comments
- Resolves extracted titles to TMDB IDs and upserts co-mention pairs into reddit_pairs

ENV
----
DATABASE_URL           Postgres URL (asyncpg). Example: postgresql+asyncpg://tvuser:tvpass@db:5432/tvrecs
TMDB_API_KEY           your TMDB key (required if the local /api/tmdb isn't available)
REDDIT_CLIENT_ID       Reddit script app client_id
REDDIT_CLIENT_SECRET   Reddit script app client_secret
REDDIT_USER_AGENT      Something like: tvrecs/0.1 by yourusername
REDDIT_SUB             subreddit to search (default: televisionsuggestions)
FAVORITES_USER_ID      user id to use (default: 1)
SEARCH_LIMIT           threads per query variant (default: 8)
QUERY_TIMESPAN         'year' | 'month' | 'week' | 'all' (default: year)
MAX_THREADS_PER_FAV    cap threads per favorite (default: 40)
TOP_COMMENTS_PER_THREAD how many top-level comments to scan (default: 40)
REDDIT_SLOWDOWN_SEC    sleep between HTTP calls to avoid 429 (float, default: 0.4)

Notes
-----
- This module only uses the OAuth endpoints: https://oauth.reddit.com/...
- If you still see 403, double-check creds are correct and the app type is "script".
- Pairs are stored canonical (a < b).
"""

from __future__ import annotations
import asyncio
import os
import time
from dataclasses import dataclass
from typing import Iterable, List, Tuple, Dict, Any, Optional, Set

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

# ---------- Config ----------

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://tvuser:tvpass@db:5432/tvrecs")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "tvrecs/0.1 by unknown")

REDDIT_SUB = os.getenv("REDDIT_SUB", "televisionsuggestions")
FAVORITES_USER_ID = int(os.getenv("FAVORITES_USER_ID", "1"))

SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "8"))
QUERY_TIMESPAN = os.getenv("QUERY_TIMESPAN", "year")
MAX_THREADS_PER_FAV = int(os.getenv("MAX_THREADS_PER_FAV", "40"))
TOP_COMMENTS_PER_THREAD = int(os.getenv("TOP_COMMENTS_PER_THREAD", "40"))
REDDIT_SLOWDOWN_SEC = float(os.getenv("REDDIT_SLOWDOWN_SEC", "0.4"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

def log(level: str, msg: str):
    if level == "DEBUG" and LOG_LEVEL not in ("DEBUG",):
        return
    print(f"{level}:{__name__}:{msg}", flush=True)

# ---------- TMDB helpers ----------

async def tmdb_get_title(tmdb_id: int) -> Optional[str]:
    """Return primary TMDB 'name' for a TV show id."""
    # Try local proxy if present
    url_local = f"http://localhost:8000/api/tmdb/details/{tmdb_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url_local)
            if r.status_code == 200:
                data = r.json()
                name = data.get("name") or data.get("title")
                if name:
                    return name
    except Exception as e:
        log("DEBUG", f"tmdb local fail: {e}")

    if not TMDB_API_KEY:
        return None

    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params={"api_key": TMDB_API_KEY})
            if r.status_code == 200:
                data = r.json()
                return data.get("name") or data.get("original_name")
    except Exception as e:
        log("DEBUG", f"tmdb remote fail: {e}")
    return None

# lightweight resolver using local API, then TMDB search
async def resolve_title_to_tmdb(title: str) -> Optional[int]:
    title = title.strip()
    if not title:
        return None

    # local
    url_local = "http://localhost:8000/api/tmdb/search"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url_local, params={"q": title, "limit": 5})
            if r.status_code == 200:
                items = r.json() or []
                for it in items:
                    if it.get("media_type") == "tv":
                        return int(it["id"])
    except Exception as e:
        log("DEBUG", f"local search fail: {e}")

    if not TMDB_API_KEY:
        return None

    # remote
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.themoviedb.org/3/search/tv",
                params={"api_key": TMDB_API_KEY, "query": title, "include_adult": "false", "page": 1},
                headers={"Accept": "application/json"}
            )
            if r.status_code == 200:
                data = r.json()
                results = data.get("results") or []
                if results:
                    return int(results[0]["id"])
    except Exception as e:
        log("DEBUG", f"tmdb search fail: {e}")
    return None

# ---------- Simple title extraction ----------

STOPWORDS = {"the","and","or","to","for","of","a","an","is","in","on","by","it","my","your","our","with","that","this","are","was","be"}

def guess_titles(text: str, max_len: int = 5) -> List[str]:
    """
    Very simple heuristic:
    - keep quoted strings
    - keep title-cased ngrams upto length max_len
    - filter out obvious junk
    """
    import re
    titles: Set[str] = set()

    # quoted
    for m in re.finditer(r'["“](.+?)["”]', text):
        t = m.group(1).strip()
        if 2 <= len(t) <= 80:
            titles.add(t)

    # title-cased ngrams
    words = re.findall(r"[A-Za-z][A-Za-z'&:-]*", text)
    n = len(words)
    for i in range(n):
        for k in range(1, max_len+1):
            if i+k > n: break
            seg = words[i:i+k]
            # title case if most words start with capital letter
            caps = sum(w[0].isupper() for w in seg)
            if caps >= max(1, int(0.6*len(seg))):
                cand = " ".join(seg)
                lo = cand.lower()
                if any(sw == lo for sw in STOPWORDS): 
                    continue
                if len(cand) < 3:
                    continue
                titles.add(cand)

    # remove fragments that are substrings of better/longer titles
    out = sorted(titles, key=len)
    pruned: List[str] = []
    for t in out:
        if not any((t != u and t in u) for u in titles):
            pruned.append(t)
    return pruned[:25]

async def extract_and_resolve(text: str) -> Tuple[List[str], List[int]]:
    titles = guess_titles(text)
    ids: List[int] = []
    for t in titles:
        tid = await resolve_title_to_tmdb(t)
        if tid:
            ids.append(tid)
    # unique while preserving order
    seen = set()
    ids = [x for x in ids if not (x in seen or seen.add(x))]
    return titles, ids

# ---------- Reddit OAuth ----------

_token_cache: Tuple[str, float] | None = None

async def reddit_oauth_token() -> str:
    global _token_cache
    # cached for 30 minutes
    now = time.time()
    if _token_cache and now < _token_cache[1]:
        return _token_cache[0]

    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        raise RuntimeError("Missing Reddit credentials: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET")

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": REDDIT_USER_AGENT},
        )
        r.raise_for_status()
        tok = r.json()["access_token"]
        _token_cache = (tok, now + 30*60)
        return tok

async def r_get(url: str, params: Dict[str, Any] | None = None) -> httpx.Response:
    """GET with OAuth and small slowdown."""
    tok = await reddit_oauth_token()
    await asyncio.sleep(REDDIT_SLOWDOWN_SEC)
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {tok}",
                "User-Agent": REDDIT_USER_AGENT,
                "Accept": "application/json",
            },
        )
        return r

async def search_threads_oauth(query: str, limit: int = 8, t: str = "year") -> List[Dict[str, Any]]:
    url = f"https://oauth.reddit.com/r/{REDDIT_SUB}/search"
    params = {
        "q": query,
        "restrict_sr": "1",
        "sort": "top",
        "t": t,
        "limit": str(limit),
        "type": "link",
        "include_over_18": "on",
    }
    r = await r_get(url, params=params)
    if r.status_code == 200:
        j = r.json()
        ch = j.get("data", {}).get("children", [])
        out = []
        for c in ch:
            d = c.get("data", {})
            out.append(d)
        return out
    else:
        log("DEBUG", f"search {query!r} -> {r.status_code} {r.text[:200]}")
        return []

async def fetch_comments_oauth(permalink: str) -> List[Dict[str, Any]]:
    # permalink like /r/televisionsuggestions/comments/xxxx/title/
    # Use OAuth endpoint:
    if permalink.startswith("http"):
        # strip domain
        idx = permalink.find("/r/")
        if idx > 0:
            permalink = permalink[idx:]
    url = f"https://oauth.reddit.com{permalink}.json"
    r = await r_get(url, params={"limit":"500"})
    if r.status_code == 200:
        try:
            j = r.json()
        except Exception:
            return []
        if isinstance(j, list) and len(j) >= 2:
            # comments are in second element
            comments = j[1].get("data", {}).get("children", [])
            rows = []
            for c in comments:
                d = c.get("data", {})
                if d.get("body"):
                    rows.append(d)
            return rows
    else:
        log("DEBUG", f"comments {permalink} -> {r.status_code}")
    return []

# ---------- DB helpers ----------

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, echo=(LOG_LEVEL=="DEBUG"))

async def fetch_user_favorites(session: AsyncSession, user_id: int) -> List[int]:
    sql = text("SELECT tmdb_id FROM user_favorites WHERE user_id = :uid ORDER BY created_at DESC")
    rows = (await session.execute(sql, {"uid": user_id})).all()
    return [int(r[0]) for r in rows]

async def upsert_pair(session: AsyncSession, a: int, b: int, sub: str):
    if a == b:
        return
    left, right = (a, b) if a < b else (b, a)
    up_sql = text("""
        INSERT INTO reddit_pairs (tmdb_id_a, tmdb_id_b, pair_count, pair_weight, subreddits, updated_at)
        VALUES (:a, :b, 1, 1.0, ARRAY[:s], now())
        ON CONFLICT (tmdb_id_a, tmdb_id_b)
        DO UPDATE SET
            pair_count  = reddit_pairs.pair_count + 1,
            pair_weight = reddit_pairs.pair_weight + 1.0,
            subreddits  = ARRAY(SELECT DISTINCT unnest(reddit_pairs.subreddits || EXCLUDED.subreddits)),
            updated_at  = now();
    """)
    await session.execute(up_sql, {"a": left, "b": right, "s": sub})

# ---------- Core logic ----------

def make_query_variants(title: str) -> List[str]:
    q = [f'"{title}"']
    # a few relaxed variants
    q.append(title)
    if ":" in title:
        main = title.split(":")[0]
        if len(main) >= 3:
            q.append(f'"{main.strip()}"')
    return list(dict.fromkeys(q))  # dedupe, keep order

async def process_favorite(session: AsyncSession, fav_tmdb_id: int) -> int:
    """Returns number of pair upserts for this favorite."""
    base_title = await tmdb_get_title(fav_tmdb_id) or str(fav_tmdb_id)
    variants = make_query_variants(base_title)

    threads: List[Dict[str, Any]] = []
    for q in variants:
        hits = await search_threads_oauth(q, limit=SEARCH_LIMIT, t=QUERY_TIMESPAN)
        threads.extend(h for h in hits if h.get("permalink"))

    # cap to avoid explosion
    seen_ids: Set[str] = set()
    unique_threads: List[Dict[str, Any]] = []
    for th in threads:
        tid = th.get("id") or th.get("name")
        if tid and tid not in seen_ids:
            seen_ids.add(tid)
            unique_threads.append(th)
        if len(unique_threads) >= MAX_THREADS_PER_FAV:
            break

    log("INFO", f"[pairs] favorite {fav_tmdb_id} ({base_title!r}) -> {len(unique_threads)} thread hits")

    total_upserts = 0
    for th in unique_threads:
        permalink = th["permalink"]
        # gather OP + top comments text
        texts: List[str] = []
        # OP title and selftext
        if th.get("title"):
            texts.append(th["title"])
        if th.get("selftext"):
            texts.append(th["selftext"])

        comments = await fetch_comments_oauth(permalink)
        for d in comments[:TOP_COMMENTS_PER_THREAD]:
            body = d.get("body") or ""
            if body:
                texts.append(body)

        # extract & resolve
        mentioned_ids: Set[int] = set()
        for text in texts:
            _titles, ids = await extract_and_resolve(text)
            for tid in ids:
                # skip the seed itself
                if tid != fav_tmdb_id:
                    mentioned_ids.add(tid)

        # upsert pairs
        for other in mentioned_ids:
            await upsert_pair(session, fav_tmdb_id, other, REDDIT_SUB)
            total_upserts += 1

    return total_upserts

async def main():
    async with AsyncSession(engine) as session:
        favs = await fetch_user_favorites(session, FAVORITES_USER_ID)
        if not favs:
            log("INFO", f"[pairs] no favorites for user {FAVORITES_USER_ID}")
            return
        grand_total = 0
        for tmdb_id in favs:
            try:
                cnt = await process_favorite(session, tmdb_id)
                await session.commit()
                grand_total += cnt
            except httpx.HTTPStatusError as e:
                log("INFO", f"[pairs] HTTP error: {e}")
                await session.rollback()
            except Exception as e:
                log("INFO", f"[pairs] error fav {tmdb_id}: {e}")
                await session.rollback()
        log("INFO", f"[pairs] done. total pair upserts={grand_total}")

if __name__ == "__main__":
    asyncio.run(main())
