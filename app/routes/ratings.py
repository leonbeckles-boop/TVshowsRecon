# app/routes/ratings.py
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import UserRating as Rating  # <- alias to match your model name
from app.security import require_user

router = APIRouter(prefix="/ratings", tags=["ratings"])


class RatingIn(BaseModel):
    user_id: int
    tmdb_id: int
    rating: float
    title: Optional[str] = None
    seasons_completed: Optional[int] = None
    notes: Optional[str] = None


@router.get("/ratings")
async def list_ratings(
    user_id: int = Query(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict]:
    """Return ratings shaped exactly like the FE expects."""
    rows = (await db.execute(
        select(Rating).where(Rating.user_id == user_id)
    )).scalars().all()

    return [
        {
            "tmdb_id": r.tmdb_id,
            "rating": float(r.rating),
            "title": r.title,
            "seasons_completed": r.seasons_completed,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/ratings")
async def upsert_rating(
    payload: RatingIn,
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """Create or update a rating (unique on user_id + tmdb_id)."""
    row = (await db.execute(
        select(Rating).where(
            and_(Rating.user_id == payload.user_id, Rating.tmdb_id == payload.tmdb_id)
        )
    )).scalar_one_or_none()

    if row:
        row.rating = payload.rating
        row.title = payload.title
        row.seasons_completed = payload.seasons_completed
        row.notes = payload.notes
    else:
        row = Rating(
            user_id=payload.user_id,
            tmdb_id=payload.tmdb_id,
            rating=payload.rating,
            title=payload.title,
            seasons_completed=payload.seasons_completed,
            notes=payload.notes,
        )
        db.add(row)

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}
