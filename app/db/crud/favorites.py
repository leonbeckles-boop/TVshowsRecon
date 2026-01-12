# app/db/crud/favorites.py
from __future__ import annotations

from typing import List, Dict, Any
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FavoriteTMDB

def _payload_get(payload: Any, key: str, default=None):
    # Accept both Pydantic models (attribute) and dict (key)
    if hasattr(payload, key):
        return getattr(payload, key)
    if isinstance(payload, dict):
        return payload.get(key, default)
    return default

def _serialize(row: FavoriteTMDB) -> Dict[str, Any]:
    return {"tmdb_id": row.tmdb_id, "title": getattr(row, "title", None)}

async def list_favorites(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    res = await db.execute(select(FavoriteTMDB).where(FavoriteTMDB.user_id == user_id))
    rows = res.scalars().all()
    return [_serialize(r) for r in rows]

async def add_favorite(db: AsyncSession, user_id: int, payload: Any) -> Dict[str, Any]:
    tmdb_id = int(_payload_get(payload, "tmdb_id"))
    title = _payload_get(payload, "title", None)

    # Upsert-ish: if exists, return it; else insert
    res = await db.execute(
        select(FavoriteTMDB).where(
            (FavoriteTMDB.user_id == user_id) & (FavoriteTMDB.tmdb_id == tmdb_id)
        )
    )
    existing = res.scalar_one_or_none()
    if existing:
        # Optional: update title if provided
        if title:
            setattr(existing, "title", title)
            await db.commit()
            await db.refresh(existing)
        return _serialize(existing)

    obj = FavoriteTMDB(user_id=user_id, tmdb_id=tmdb_id)
    # Some schemas include title; add if your table has that column
    if hasattr(FavoriteTMDB, "title"):
        setattr(obj, "title", title)

    db.add(obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Re-fetch and return (race condition safe)
        res = await db.execute(
            select(FavoriteTMDB).where(
                (FavoriteTMDB.user_id == user_id) & (FavoriteTMDB.tmdb_id == tmdb_id)
            )
        )
        existing = res.scalar_one()
        return _serialize(existing)

    await db.refresh(obj)
    return _serialize(obj)

async def remove_favorite(db: AsyncSession, user_id: int, tmdb_id: int) -> None:
    await db.execute(
        delete(FavoriteTMDB).where(
            (FavoriteTMDB.user_id == user_id) & (FavoriteTMDB.tmdb_id == tmdb_id)
        )
    )
    await db.commit()
