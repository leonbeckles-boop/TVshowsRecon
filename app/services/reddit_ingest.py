from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import httpx
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

logger = logging.getLogger(__name__)

load_dotenv()

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_SECRET") or os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "tvrecs/1.0")
REDDIT_SUBS = [
    s.strip()
    for s in os.getenv("REDDIT_SUBS", "televisionsuggestions").split(",")
    if s.strip()
]

INTERNAL_BASE = os.getenv("INTERNAL_BASE_URL", "http://127.0.0.1:8000")
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("RENDER_DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("SQLALCHEMY_DATABASE_URL")
)

# Aggressive stop-list for ambiguous/common titles.
STOP_TITLES: Set[str] = {
    "you",
    "from",
    "see",
    "dark",
    "community",
    "friends",
    "soap",
    "girls",
    "love",
    "mom",
    "evil",
    "lost",
    "shameless",
    "episodes",
    "episode",
    "the night",
    "night",
    "once",
    "looking",
    "paradise",
    "maid",
    "greek",
    "life",
    "next",
    "found",
    "boss",
    "heroes",
    "skins",
    "glow",
    "teachers",
    "reason",
    "reunion",
    "level",
    "chance",
    "between",
    "awake",
    "crash",
    "drive",
    "chosen",
    "panic",
    "ghosts",
    "medium",
    "single",
    "party",
}

TITLE_MIN_LEN = 4
TITLE_MIN_WORDS_FOR_RELAXED_MATCH = 2
SINGLE_WORD_MIN_LEN = 7
SEARCH_TITLE_CAP = 20

RECOMMENDATION_CONTEXT_PATTERNS = [
    r"\bshows?\s+like\b",
    r"\bsimilar\s+to\b",
    r"\brecommend(?:ed|ations?)?\b",
    r"\bwhat\s+should\s+i\s+watch\b",
    r"\bwhat\s+to\s+watch\b",
    r"\bif\s+i\s+liked\b",
    r"\blooking\s+for\s+(?:a\s+)?show\b",
    r"\bneed\s+a\s+show\b",
    r"\bwatch\s+next\b",
]


def _normalize_database_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    raw = url.strip().strip('"').strip("'")
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        parsed = make_url(raw)
        if "+" not in parsed.drivername:
            parsed = parsed.set(drivername="postgresql+asyncpg")
            return str(parsed)
    return raw


def _require_env() -> None:
    missing = []
    if not REDDIT_CLIENT_ID:
        missing.append("REDDIT_CLIENT_ID")
    if not REDDIT_SECRET:
        missing.append("REDDIT_SECRET or REDDIT_CLIENT_SECRET")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    if not DATABASE_URL:
        raise RuntimeError(
            "Missing database URL. Set DATABASE_URL, RENDER_DATABASE_URL, POSTGRES_URL, or SQLALCHEMY_DATABASE_URL."
        )


def _utc_from_epoch(epoch: Optional[float]) -> Optional[datetime]:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    except Exception:
        return None


def _norm_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^\w\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _slugish(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^\w\s]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _has_recommendation_context(text_value: str) -> bool:
    norm = _norm_text(text_value)
    return any(re.search(pattern, norm) for pattern in RECOMMENDATION_CONTEXT_PATTERNS)


def _title_word_count(title: str) -> int:
    return len([p for p in re.split(r"\s+", title.strip()) if p])


def _is_allowed_title(title: str) -> bool:
    key = _slugish(title)
    if len(key) < TITLE_MIN_LEN:
        return False
    if key in STOP_TITLES:
        return False

    word_count = _title_word_count(title)
    if word_count <= 1 and len(key) < SINGLE_WORD_MIN_LEN:
        return False

    return True


async def _reddit_token() -> str:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(REDDIT_CLIENT_ID, REDDIT_SECRET),
            headers={"User-Agent": REDDIT_USER_AGENT},
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def fetch_top_week(
    token: str, sub: str, limit: int = 100
) -> List[Dict[str, Any]]:
    url = f"https://oauth.reddit.com/r/{sub}/top"
    params = {"t": "week", "limit": str(limit)}
    headers = {"Authorization": f"bearer {token}", "User-Agent": REDDIT_USER_AGENT}
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        js = r.json()
        return [
            it["data"]
            for it in (js.get("data", {}).get("children") or [])
            if isinstance(it, dict) and "data" in it
        ]


async def fetch_search_for_titles(
    token: str, sub: str, titles: Sequence[str], per_title: int = 30
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not titles:
        return out

    headers = {"Authorization": f"bearer {token}", "User-Agent": REDDIT_USER_AGENT}
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        for title in titles[:SEARCH_TITLE_CAP]:
            q = f'title:"{title}"'
            url = f"https://oauth.reddit.com/r/{sub}/search"
            params = {
                "q": q,
                "restrict_sr": "true",
                "sort": "top",
                "t": "year",
                "limit": str(per_title),
            }
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                js = r.json()
                items = [
                    it["data"]
                    for it in (js.get("data", {}).get("children") or [])
                    if isinstance(it, dict) and "data" in it
                ]
                out.extend(items)
            except Exception as exc:
                logger.warning(
                    "reddit_ingest: search failed for %r in r/%s: %s", title, sub, exc
                )
    return out


async def get_user_favourites_titles(user_id: int) -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{INTERNAL_BASE}/api/library/{user_id}/favorites")
            r.raise_for_status()
            js = r.json()
            items = js if isinstance(js, list) else (
                js.get("items") if isinstance(js, dict) else []
            )
            titles: List[str] = []
            for item in items:
                name = item.get("title") or item.get("name")
                if isinstance(name, str) and name.strip():
                    titles.append(name.strip())
            return titles
    except Exception as exc:
        logger.warning(
            "reddit_ingest: unable to fetch favourites for user %s: %s", user_id, exc
        )
        return []


async def _get_engine() -> AsyncEngine:
    return create_async_engine(
        _normalize_database_url(DATABASE_URL), future=True, pool_pre_ping=True
    )


async def _get_table_columns(
    session: AsyncSession, table_name: str
) -> Dict[str, Dict[str, Any]]:
    q = text(
        """
        SELECT column_name, is_nullable, data_type, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table_name
        """
    )
    rows = (await session.execute(q, {"table_name": table_name})).mappings().all()
    return {row["column_name"]: dict(row) for row in rows}


async def _ensure_reddit_post_mentions_table(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS reddit_post_mentions (
                post_id BIGINT NOT NULL,
                tmdb_id BIGINT NOT NULL,
                PRIMARY KEY (post_id, tmdb_id)
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_reddit_post_mentions_post_id
            ON reddit_post_mentions (post_id)
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_reddit_post_mentions_tmdb_id
            ON reddit_post_mentions (tmdb_id)
            """
        )
    )


async def _load_show_catalog(session: AsyncSession) -> List[Dict[str, Any]]:
    # Your shows table uses `title`, not `name`.
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    show_id,
                    title,
                    COALESCE(vote_count, 0) AS vote_count,
                    COALESCE(vote_average, 0) AS vote_average,
                    COALESCE(popularity, 0) AS popularity,
                    first_air_date
                FROM shows
                WHERE title IS NOT NULL
                  AND title <> ''
                """
            )
        )
    ).mappings().all()

    if not rows:
        raise RuntimeError("Unable to load show catalog from the shows table.")

    catalog: List[Dict[str, Any]] = []
    seen: Set[int] = set()

    for row in rows:
        show_id = row.get("show_id")
        title = row.get("title")
        if show_id is None or not isinstance(title, str) or not title.strip():
            continue

        sid = int(show_id)
        if sid in seen:
            continue

        seen.add(sid)
        catalog.append(
            {
                "show_id": sid,
                "title": title.strip(),
                "vote_count": int(row.get("vote_count") or 0),
                "vote_average": float(row.get("vote_average") or 0.0),
                "popularity": float(row.get("popularity") or 0.0),
                "first_air_date": row.get("first_air_date"),
            }
        )

    return catalog


def _catalog_rank_key(item: Dict[str, Any]) -> Tuple[float, float, str]:
    # Higher is better.
    return (
        float(item.get("vote_count") or 0),
        float(item.get("popularity") or 0.0) + float(item.get("vote_average") or 0.0),
        str(item.get("first_air_date") or ""),
    )


def _build_match_index(
    catalog: Sequence[Dict[str, Any]]
) -> Dict[str, Tuple[int, str]]:
    # One normalized title -> one canonical show.
    best_by_key: Dict[str, Dict[str, Any]] = {}

    for item in catalog:
        title = item["title"]
        if not _is_allowed_title(title):
            continue

        key = _slugish(title)
        current = best_by_key.get(key)
        if current is None or _catalog_rank_key(item) > _catalog_rank_key(current):
            best_by_key[key] = item

    out: Dict[str, Tuple[int, str]] = {}
    for key, item in best_by_key.items():
        out[key] = (int(item["show_id"]), str(item["title"]))
    return out


def _match_titles(
    post: Dict[str, Any], match_index: Dict[str, Tuple[int, str]]
) -> List[Tuple[int, str]]:
    title_text = str(post.get("title") or "")
    body_text = str(post.get("selftext") or "")
    hay = " ".join([title_text, body_text])
    norm = f" {_norm_text(hay)} "
    has_context = _has_recommendation_context(hay)

    found: Dict[int, str] = {}

    for norm_title, hit in match_index.items():
        show_id, title = hit
        if f" {norm_title} " not in norm:
            continue

        word_count = _title_word_count(title)

        # Stricter rules for single-word titles.
        if word_count < TITLE_MIN_WORDS_FOR_RELAXED_MATCH:
            # For one-word titles, only accept them in recommendation-oriented posts,
            # and only if they are not on the stop-list.
            if not has_context:
                continue

        found[show_id] = title

    return sorted(found.items(), key=lambda x: x[1].lower())


def _dedupe_posts(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        reddit_id = str(item.get("id") or "").strip()
        if not reddit_id or reddit_id in seen:
            continue
        seen.add(reddit_id)
        out.append(item)
    return out


async def _upsert_reddit_post(
    session: AsyncSession,
    post: Dict[str, Any],
    reddit_posts_columns: Dict[str, Dict[str, Any]],
) -> Optional[int]:
    available = set(reddit_posts_columns)
    row: Dict[str, Any] = {}
    mapping = {
        "reddit_id": str(post.get("id") or "").strip() or None,
        "subreddit": post.get("subreddit"),
        "title": post.get("title"),
        "selftext": post.get("selftext"),
        "author": post.get("author"),
        "score": post.get("score"),
        "num_comments": post.get("num_comments"),
        "permalink": post.get("permalink"),
        "url": post.get("url"),
        "created_utc": _utc_from_epoch(post.get("created_utc")),
        "fetched_at": datetime.now(timezone.utc),
        "raw_json": json.dumps(post),
        "tmdb_id": None,
        "show_id": None,
    }
    for col, val in mapping.items():
        if col in available:
            row[col] = val

    if "reddit_id" not in row or not row["reddit_id"]:
        return None

    cols = ", ".join(row.keys())
    binds = ", ".join(f":{k}" for k in row.keys())
    updates = ", ".join(
        f"{k} = EXCLUDED.{k}" for k in row.keys() if k not in {"reddit_id"}
    )
    stmt = text(
        f"""
        INSERT INTO reddit_posts ({cols})
        VALUES ({binds})
        ON CONFLICT (reddit_id) DO UPDATE SET
        {updates}
        RETURNING id
        """
    )
    try:
        res = await session.execute(stmt, row)
        return int(res.scalar_one())
    except Exception:
        await session.rollback()
        res = await session.execute(
            text("SELECT id FROM reddit_posts WHERE reddit_id = :reddit_id"),
            {"reddit_id": row["reddit_id"]},
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            return int(existing)
        raise


async def _insert_post_mentions(
    session: AsyncSession,
    post_id: int,
    tmdb_ids: Sequence[int],
    reddit_post_mentions_columns: Dict[str, Dict[str, Any]],
) -> List[int]:
    available = set(reddit_post_mentions_columns)
    if not {"post_id", "tmdb_id"}.issubset(available):
        return []

    inserted_ids: List[int] = []
    stmt = text(
        """
        INSERT INTO reddit_post_mentions (post_id, tmdb_id)
        VALUES (:post_id, :tmdb_id)
        ON CONFLICT DO NOTHING
        RETURNING tmdb_id
        """
    )
    for tmdb_id in sorted(set(int(x) for x in tmdb_ids)):
        res = await session.execute(stmt, {"post_id": post_id, "tmdb_id": tmdb_id})
        returned = res.scalar_one_or_none()
        if returned is not None:
            inserted_ids.append(int(returned))
    return inserted_ids


async def _upsert_pairs(
    session: AsyncSession,
    tmdb_ids: Sequence[int],
    subreddit: str,
    reddit_pairs_columns: Dict[str, Dict[str, Any]],
) -> int:
    available = set(reddit_pairs_columns)
    if not {"tmdb_id_a", "tmdb_id_b"}.issubset(available):
        return 0

    unique_ids = sorted(set(int(x) for x in tmdb_ids))
    if len(unique_ids) < 2:
        return 0

    supports_pair_count = "pair_count" in available
    supports_pair_weight = "pair_weight" in available
    supports_subreddits = "subreddits" in available
    supports_updated_at = "updated_at" in available

    count = 0
    for i in range(len(unique_ids)):
        for j in range(i + 1, len(unique_ids)):
            a = unique_ids[i]
            b = unique_ids[j]
            fields = ["tmdb_id_a", "tmdb_id_b"]
            values = [":tmdb_id_a", ":tmdb_id_b"]
            payload: Dict[str, Any] = {
                "tmdb_id_a": a,
                "tmdb_id_b": b,
                "subreddit": subreddit,
            }

            if supports_pair_count:
                fields.append("pair_count")
                values.append(":pair_count")
                payload["pair_count"] = 1
            if supports_pair_weight:
                fields.append("pair_weight")
                values.append(":pair_weight")
                payload["pair_weight"] = 1.0
            if supports_subreddits:
                fields.append("subreddits")
                values.append("ARRAY[:subreddit]::text[]")
            if supports_updated_at:
                fields.append("updated_at")
                values.append(":updated_at")
                payload["updated_at"] = datetime.now(timezone.utc)

            updates: List[str] = []
            if supports_pair_count:
                updates.append("pair_count = COALESCE(reddit_pairs.pair_count, 0) + 1")
            if supports_pair_weight:
                updates.append(
                    "pair_weight = COALESCE(reddit_pairs.pair_weight, 0) + 1"
                )
            if supports_subreddits:
                updates.append(
                    "subreddits = (SELECT ARRAY(SELECT DISTINCT unnest(COALESCE(reddit_pairs.subreddits, ARRAY[]::text[]) || EXCLUDED.subreddits)))"
                )
            if supports_updated_at:
                updates.append("updated_at = EXCLUDED.updated_at")

            stmt = text(
                f"""
                INSERT INTO reddit_pairs ({', '.join(fields)})
                VALUES ({', '.join(values)})
                ON CONFLICT (tmdb_id_a, tmdb_id_b) DO UPDATE SET
                {', '.join(updates) if updates else 'tmdb_id_a = EXCLUDED.tmdb_id_a'}
                """
            )
            await session.execute(stmt, payload)
            count += 1
    return count


async def run_ingest(
    user_id: Optional[int] = None,
    subreddits: Optional[Sequence[str]] = None,
    top_limit: int = 100,
    search_per_title: int = 15,
) -> Dict[str, Any]:
    _require_env()
    token = await _reddit_token()

    chosen_subs = [s.strip() for s in (subreddits or REDDIT_SUBS) if s.strip()]
    if not chosen_subs:
        raise RuntimeError("No subreddits configured. Set REDDIT_SUBS or pass --subs.")

    all_items: List[Dict[str, Any]] = []
    for sub in chosen_subs:
        try:
            items = await fetch_top_week(token, sub, limit=top_limit)
            all_items.extend(items)
            logger.info("[Reddit] fetched top/week from r/%s: %s posts", sub, len(items))
        except Exception as exc:
            logger.warning("reddit_ingest: top-week fetch failed for r/%s: %s", sub, exc)

    fav_titles: List[str] = []
    if user_id is not None:
        fav_titles = await get_user_favourites_titles(user_id)
        if fav_titles:
            logger.info(
                "[Reddit] user %s favourites loaded: %s titles",
                user_id,
                len(fav_titles),
            )
            for sub in chosen_subs:
                more = await fetch_search_for_titles(
                    token, sub, fav_titles, per_title=search_per_title
                )
                logger.info("[Reddit] fetched title-search from r/%s: %s posts", sub, len(more))
                all_items.extend(more)

    all_items = _dedupe_posts(all_items)

    engine = await _get_engine()
    saved = 0
    failed = 0
    matched_posts = 0
    mentions_inserted = 0
    pairs_updated = 0
    skipped_existing_mentions = 0

    try:
        async with engine.begin() as conn:
            session = AsyncSession(bind=conn, expire_on_commit=False)

            await _ensure_reddit_post_mentions_table(session)

            reddit_posts_columns = await _get_table_columns(session, "reddit_posts")
            reddit_post_mentions_columns = await _get_table_columns(
                session, "reddit_post_mentions"
            )
            reddit_pairs_columns = await _get_table_columns(session, "reddit_pairs")

            catalog = await _load_show_catalog(session)
            match_index = _build_match_index(catalog)
            logger.info("[Reddit] loaded show catalog: %s canonical titles", len(match_index))

            for post in all_items:
                try:
                    matches = _match_titles(post, match_index)
                    if not matches:
                        continue

                    matched_posts += 1
                    tmdb_ids = [show_id for show_id, _title in matches]
                    post_id = await _upsert_reddit_post(session, post, reddit_posts_columns)
                    if post_id is None:
                        failed += 1
                        continue

                    saved += 1

                    new_mentions = await _insert_post_mentions(
                        session, post_id, tmdb_ids, reddit_post_mentions_columns
                    )
                    mentions_inserted += len(new_mentions)

                    if len(new_mentions) >= 2:
                        pairs_updated += await _upsert_pairs(
                            session,
                            new_mentions,
                            str(post.get("subreddit") or ""),
                            reddit_pairs_columns,
                        )
                    else:
                        skipped_existing_mentions += 1

                except Exception as exc:
                    failed += 1
                    logger.exception(
                        "reddit_ingest: failed processing reddit_id=%s: %s",
                        post.get("id"),
                        exc,
                    )

            await session.commit()
    finally:
        await engine.dispose()

    result = {
        "fetched": len(all_items),
        "saved": saved,
        "failed": failed,
        "matched_posts": matched_posts,
        "mentions_inserted": mentions_inserted,
        "pairs_updated": pairs_updated,
        "skipped_existing_mentions": skipped_existing_mentions,
        "user_id": user_id,
        "subreddits": chosen_subs,
        "favourite_titles_used": len(fav_titles),
    }

    logger.info(
        "[Reddit] Ingest complete. user_id=%s fetched=%s saved=%s matched_posts=%s mentions_inserted=%s pairs_updated=%s skipped_existing_mentions=%s failed=%s",
        user_id,
        result["fetched"],
        result["saved"],
        result["matched_posts"],
        result["mentions_inserted"],
        result["pairs_updated"],
        result["skipped_existing_mentions"],
        result["failed"],
    )
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest Reddit posts into WhatNext Reddit tables."
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Optional user id to bias search toward favourite titles.",
    )
    parser.add_argument(
        "--subs",
        type=str,
        default=None,
        help="Comma-separated subreddit list. Defaults to REDDIT_SUBS.",
    )
    parser.add_argument(
        "--top-limit",
        type=int,
        default=100,
        help="Top/week post limit per subreddit.",
    )
    parser.add_argument(
        "--search-per-title",
        type=int,
        default=15,
        help="Search result limit per favourite title.",
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO", help="Logging level, e.g. INFO or DEBUG."
    )
    return parser.parse_args()


async def _amain() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    subs = [s.strip() for s in args.subs.split(",")] if args.subs else None
    result = await run_ingest(
        user_id=args.user_id,
        subreddits=subs,
        top_limit=args.top_limit,
        search_per_title=args.search_per_title,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_amain())