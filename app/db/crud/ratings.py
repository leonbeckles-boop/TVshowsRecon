# app/db/crud/ratings.py
from __future__ import annotations

from typing import Dict, Any, List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserRating

def _serialize(r: UserRating) -> Dict[str, Any]:
    return dict(
        id=r.id,
        tmdb_id=r.tmdb_id,
        title=getattr(r, "title", None),
        rating=r.rating,
        watched_at=r.watched_at,
        seasons_completed=getattr(r, "seasons_completed", None),
        notes=getattr(r, "notes", None),
    )

async def list_ratings(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    res = await db.execute(select(UserRating).where(UserRating.user_id == user_id))
    rows = res.scalars().all()
    return [_serialize(r) for r in rows]

async def create_or_upsert_rating(db: AsyncSession, user_id: int, dto: Any) -> Dict[str, Any]:
    """
    Upsert by (user_id, tmdb_id).
    dto is a Pydantic model (RatingIn) with:
      tmdb_id: int
      title: str | None
      rating: float
      watched_at: datetime | None
      seasons_completed: int | None
      notes: str | None
    """
    tmdb_id = int(getattr(dto, "tmdb_id"))
    res = await db.execute(
        select(UserRating).where(
            (UserRating.user_id == user_id) & (UserRating.tmdb_id == tmdb_id)
        )
    )
    existing = res.scalar_one_or_none()
    if existing:
        # Update fields if provided
        for k in ("title", "rating", "watched_at", "seasons_completed", "notes"):
            v = getattr(dto, k, None)
            if v is not None:
                setattr(existing, k, v)
        await db.commit()
        await db.refresh(existing)
        return _serialize(existing)

    obj = UserRating(
        user_id=user_id,
        tmdb_id=tmdb_id,
        title=getattr(dto, "title", None),
        rating=float(getattr(dto, "rating")),
        watched_at=getattr(dto, "watched_at", None),
        seasons_completed=getattr(dto, "seasons_completed", None),
        notes=getattr(dto, "notes", None),
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _serialize(obj)

async def patch_rating(db: AsyncSession, user_id: int, tmdb_id: int, fields: Dict[str, Any]) -> Dict[str, Any] | None:
    res = await db.execute(
        select(UserRating).where(
            (UserRating.user_id == user_id) & (UserRating.tmdb_id == tmdb_id)
        )
    )
    obj = res.scalar_one_or_none()
    if not obj:
        return None
    for k, v in fields.items():
        if hasattr(obj, k) and v is not None:
            setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return _serialize(obj)

async def delete_rating(db: AsyncSession, user_id: int, tmdb_id: int) -> None:
    await db.execute(
        delete(UserRating).where(
            (UserRating.user_id == user_id) & (UserRating.tmdb_id == tmdb_id)
        )
    )
    await db.commit()
