# app/routes/ratings_path.py  (patched)
from __future__ import annotations
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Body
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

# DB/session + models
from app.database import get_async_db
from app.db_models import UserRating

# Auth dependency (use whatever you already use elsewhere)
try:
    from app.routes.auth import require_user, require_user_match
except Exception:
    from app.security import require_user, require_user_match  # fallback

# IMPORTANT: expose under /api/users/...
# We'll mount with prefix="/api" in main, so final paths are /api/users/{user_id}/ratings
router = APIRouter(prefix="/users", tags=["ratings"])

# ── Schemas ───────────────────────────────────────────────────────────

class RatingIn(BaseModel):
    tmdb_id: int = Field(ge=1)
    rating: float = Field(ge=0, le=100)
    title: Optional[str] = None
    seasons_completed: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None

class RatingOut(BaseModel):
    tmdb_id: int
    rating: float
    title: Optional[str] = None
    seasons_completed: Optional[int] = None
    notes: Optional[str] = None

class RatingsResponse(BaseModel):
    user_id: int
    ratings: List[RatingOut]

# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/{user_id}/ratings", response_model=RatingsResponse, summary="List ratings for a user (path style)")
async def list_ratings_for_user(
    user_id: int = Path(ge=1),
    _: Any = Depends(require_user_match),
    db: AsyncSession = Depends(get_async_db),
):
    rows = (await db.execute(
        select(UserRating).where(UserRating.user_id == user_id)
    )).scalars().all()

    return {
        "user_id": user_id,
        "ratings": [
            RatingOut(
                tmdb_id=r.tmdb_id,
                rating=float(r.rating),
                title=r.title,
                seasons_completed=r.seasons_completed,
                notes=r.notes,
            )
            for r in rows
        ],
    }

@router.post("/{user_id}/ratings", summary="Upsert a rating for a user (path style)")
async def upsert_rating_for_user(
    user_id: int = Path(ge=1),
    payload: RatingIn = Body(...),
    _: Any = Depends(require_user_match),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    existing = (await db.execute(
        select(UserRating).where(
            and_(UserRating.user_id == user_id, UserRating.tmdb_id == payload.tmdb_id)
        )
    )).scalar_one_or_none()

    if existing:
        existing.rating = payload.rating
        existing.title = payload.title
        existing.seasons_completed = payload.seasons_completed
        existing.notes = payload.notes
    else:
        db.add(UserRating(
            user_id=user_id,
            tmdb_id=payload.tmdb_id,
            rating=payload.rating,
            title=payload.title,
            seasons_completed=payload.seasons_completed,
            notes=payload.notes,
        ))

    await db.commit()
    return {"ok": True}
