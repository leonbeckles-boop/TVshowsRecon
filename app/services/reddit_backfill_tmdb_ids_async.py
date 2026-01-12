
# app/services/reddit_backfill_tmdb_ids_async.py (patched v2)
import asyncio, os, logging
from typing import Dict
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from app.services.title_to_tmdb import lookup_tmdb_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://tvuser:devpass1@db:5432/tvrecs")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def backfill(limit: int=500) -> Dict[str,int]:
    scanned=inserted=0
    async with Session() as s:
        res = await s.execute(text("""
            SELECT p.id, p.title
            FROM reddit_posts p
            LEFT JOIN reddit_post_mentions m ON m.post_id = p.id
            WHERE m.post_id IS NULL
            ORDER BY p.id DESC
            LIMIT :limit
        """), {"limit": limit})
        for pid, title in res.fetchall():
            scanned += 1
            tid = lookup_tmdb_id(title or "")
            if tid:
                await s.execute(text("""
                    INSERT INTO reddit_post_mentions (post_id, tmdb_id) VALUES (:p,:t)
                    ON CONFLICT (post_id, tmdb_id) DO NOTHING
                """), {"p": pid, "t": int(tid)})
                inserted += 1
        await s.execute(text("""
            INSERT INTO reddit_scores (tmdb_id, score_reddit, updated_at)
            SELECT m.tmdb_id, COALESCE(SUM(GREATEST(p.score,0)),0)::double precision, now()
            FROM reddit_post_mentions m
            JOIN reddit_posts p ON p.id = m.post_id
            GROUP BY m.tmdb_id
            ON CONFLICT (tmdb_id) DO UPDATE
            SET score_reddit = EXCLUDED.score_reddit, updated_at = now();
        """))
        await s.execute(text("""
            INSERT INTO reddit_comentions (seed_tmdb_id, tmdb_id, weight, updated_at)
            SELECT a.tmdb_id, b.tmdb_id, COUNT(*)::double precision, now()
            FROM reddit_post_mentions a
            JOIN reddit_post_mentions b ON a.post_id=b.post_id AND a.tmdb_id<>b.tmdb_id
            GROUP BY a.tmdb_id, b.tmdb_id
            ON CONFLICT (seed_tmdb_id, tmdb_id) DO UPDATE
            SET weight = EXCLUDED.weight, updated_at = now();
        """))
        await s.commit()
    return {"scanned": scanned, "inserted_mentions": inserted}

if __name__ == "__main__":
    print(asyncio.run(backfill()))
