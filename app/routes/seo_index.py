from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import get_async_session

router = APIRouter(prefix="/api/seo", tags=["seo"])


@router.get("/shows-like-index")
async def shows_like_index(
    limit: int = 100,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Returns best shows to build SEO pages for.
    Uses vote_count + popularity as a signal.
    """

    res = await db.execute(
        text(
            """
            SELECT
                show_id,
                title
            FROM shows
            WHERE title IS NOT NULL
            ORDER BY show_id
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )

    rows = res.mappings().all()

    return [
        {
            "tmdb_id": r["show_id"],
            "title": r["title"],
        }
        for r in rows
    ]