# app/services/reddit_backfill_tmdb_ids.py
# Backfills reddit_posts.tmdb_id using (1) DB title join if available, then (2) TMDB lookup.

import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import os

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- DB bootstrap (read DATABASE_URL from env) ---
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tvuser:devpass1@db:5432/tvrecs"
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# --- Try to import any available TMDB resolvers from your codebase ---
async def resolve_tmdb_id_via_code(title: str) -> Optional[int]:
    title = (title or "").strip()
    if not title:
        return None

    # 1) app.services.title_to_tmdb
    try:
        from app.services.title_to_tmdb import title_to_tmdb_id, resolve_tmdb_id  # type: ignore
        try:
            tmdb_id = await title_to_tmdb_id(title)  # async?
            if tmdb_id:
                return int(tmdb_id)
        except TypeError:
            tmdb_id = title_to_tmdb_id(title)  # sync
            if tmdb_id:
                return int(tmdb_id)
        try:
            tmdb_id = await resolve_tmdb_id(title)  # async?
            if tmdb_id:
                return int(tmdb_id)
        except TypeError:
            tmdb_id = resolve_tmdb_id(title)  # sync
            if tmdb_id:
                return int(tmdb_id)
    except Exception:
        pass

    # 2) app.services.tmdb_service
    try:
        from app.services.tmdb_service import search_tv_first_id  # type: ignore
        try:
            tmdb_id = await search_tv_first_id(title)  # async?
        except TypeError:
            tmdb_id = search_tv_first_id(title)        # sync
        if tmdb_id:
            return int(tmdb_id)
    except Exception:
        pass

    # 3) app.services.tmdb (fallback)
    try:
        from app.services.tmdb import search_tv  # type: ignore
        try:
            results = await search_tv(title)  # async?
        except TypeError:
            results = search_tv(title)        # sync
        if results:
            # results could be list of dicts with 'id'
            first = results[0]
            tmdb_id = first.get("id")
            if tmdb_id:
                return int(tmdb_id)
    except Exception:
        pass

    return None


async def backfill_db_join(session: AsyncSession) -> int:
    """
    If a catalogue table exists with (title, tmdb_id), try an exact-lowercase join first.
    Adjust the table/column names below if yours differ.
    """
    # Try a few plausible catalogue table names
    candidate_tables = ["shows", "tvshows", "tv_shows", "titles"]
    updated_total = 0

    for table in candidate_tables:
        try:
            sql = text(f"""
                UPDATE reddit_posts rp
                SET tmdb_id = s.tmdb_id
                FROM {table} s
                WHERE rp.tmdb_id IS NULL
                  AND lower(rp.title) = lower(s.title)
                  AND s.tmdb_id IS NOT NULL
            """)
            res = await session.execute(sql)
            await session.commit()
            updated = res.rowcount or 0
            if updated:
                logger.info(f"[DB-JOIN] Matched {updated} via exact title join on table '{table}'.")
                updated_total += updated
        except Exception as e:
            # Table might not exist; ignore and continue
            logger.debug(f"[DB-JOIN] Skipped table {table}: {e}")

    return updated_total


async def backfill_tmdb_lookup(session: AsyncSession, limit: int = 200) -> int:
    """
    For remaining posts without tmdb_id, try TMDB lookups.
    """
    sel = text("""
        SELECT id, title
        FROM reddit_posts
        WHERE tmdb_id IS NULL
        ORDER BY id DESC
        LIMIT :limit
    """)
    res = await session.execute(sel, {"limit": limit})
    rows = res.fetchall()
    if not rows:
        return 0

    updated = 0
    for row in rows:
        post_id, title = row
        tmdb_id = await resolve_tmdb_id_via_code(title)
        if tmdb_id:
            try:
                upd = text("UPDATE reddit_posts SET tmdb_id = :tid WHERE id = :pid")
                await session.execute(upd, {"tid": tmdb_id, "pid": post_id})
                updated += 1
            except Exception:
                await session.rollback()
    await session.commit()
    logger.info(f"[TMDB-LOOKUP] Assigned tmdb_id to {updated} posts")
    return updated


async def refresh_reddit_scores(session: AsyncSession) -> int:
    """
    Recompute reddit_scores from reddit_posts (simple aggregate).
    """
    sql = text("""
        INSERT INTO reddit_scores (tmdb_id, score_reddit, updated_at)
        SELECT tmdb_id, COALESCE(SUM(GREATEST(score,0)), 0)::double precision, now()
        FROM reddit_posts
        WHERE tmdb_id IS NOT NULL
        GROUP BY tmdb_id
        ON CONFLICT (tmdb_id) DO UPDATE
        SET score_reddit = EXCLUDED.score_reddit,
            updated_at   = now();
    """)
    await session.execute(sql)
    await session.commit()

    res = await session.execute(text("SELECT COUNT(*) FROM reddit_scores"))
    n = int(res.scalar() or 0)
    logger.info(f"[SCORES] reddit_scores rows = {n}")
    return n


async def main():
    async with Session() as session:
        j = await backfill_db_join(session)
        l = await backfill_tmdb_lookup(session, limit=500)
        n = await refresh_reddit_scores(session)
        logger.info(f"Done. join_matches={j}, tmdb_lookups={l}, scores={n}")


if __name__ == "__main__":
    asyncio.run(main())
