# app/routes/users.py
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import FavoriteTmdb, Show, NotInterested
from app.security import require_user

router = APIRouter(prefix="/users", tags=["Users"])


def _serialize_show(s: Show) -> Dict[str, Any]:
    """Serialize a Show row in a way that matches the frontend expectations."""
    # Prefer poster_path (TMDb path or full URL), fall back to poster_url if present
    poster = getattr(s, "poster_path", None) or getattr(s, "poster_url", None) or ""
    return {
        "tmdb_id": getattr(s, "external_id", None) or getattr(s, "tmdb_id", None) or getattr(s, "show_id", None),
        "show_id": getattr(s, "show_id", None),
        "title": getattr(s, "title", None),
        "year": getattr(s, "year", None),
        "poster": poster,
        "poster_path": getattr(s, "poster_path", None),
        "poster_url": getattr(s, "poster_url", None),
    }

@router.get("/{user_id}/favorites")
async def list_favorites(user_id: int, db: AsyncSession = Depends(get_db)):
    """Return favorites as show objects (title/poster/year) for the UI."""
    try:
        # Favorites are stored as TMDb IDs in user_favorites.tmdb_id
        res = await db.execute(select(UserFavorite.tmdb_id).where(UserFavorite.user_id == user_id))
        tmdb_ids = [int(x) for x in res.scalars().all()]
        if not tmdb_ids:
            return []

        # Some datasets use shows.show_id as TMDb id; keep compatibility by matching either show_id or external_id/tmdb_id.
        q = (
            select(Show)
            .where(
                (Show.show_id.in_(tmdb_ids))
                | (Show.external_id.in_([str(x) for x in tmdb_ids]))
                | (Show.tmdb_id.in_(tmdb_ids))
            )
        )
        show_res = await db.execute(q)
        shows = show_res.scalars().all()

        # Preserve input order as much as possible
        by_tmdb = {}
        for s in shows:
            key = getattr(s, "show_id", None) or getattr(s, "tmdb_id", None) or getattr(s, "external_id", None)
            try:
                key = int(key)
            except Exception:
                pass
            by_tmdb[key] = s

        out = []
        for tid in tmdb_ids:
            s = by_tmdb.get(tid) or by_tmdb.get(str(tid))
            if s:
                out.append(_serialize_show(s))
            else:
                out.append({"tmdb_id": tid, "show_id": tid, "title": None, "year": None, "poster": ""})
        return out
    except Exception:
        # If any statement fails, ensure the session is usable for subsequent requests
        try:
            await db.rollback()
        except Exception:
            pass
        raise
@router.post("/{user_id}/favorites/{tmdb_id}")
async def add_favorite(
    user_id: int,
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    existing = (
        await db.execute(
            select(FavoriteTmdb).where(
                and_(FavoriteTmdb.user_id == user_id, FavoriteTmdb.tmdb_id == tmdb_id)
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(FavoriteTmdb(user_id=user_id, tmdb_id=tmdb_id))
        await db.commit()

    return {"ok": True}


@router.delete("/{user_id}/favorites/{tmdb_id}")
async def remove_favorite(
    user_id: int,
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(FavoriteTmdb).where(
                and_(FavoriteTmdb.user_id == user_id, FavoriteTmdb.tmdb_id == tmdb_id)
            )
        )
    ).scalar_one_or_none()

    if row:
        await db.delete(row)
        await db.commit()

    return {"ok": True}


@router.post("/{user_id}/not_interested/{tmdb_id}")
async def hide_show_path(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    exists = (await db.execute(
        select(NotInterested).where(
            and_(NotInterested.user_id == user_id, NotInterested.tmdb_id == tmdb_id)
        )
    )).scalar_one_or_none()
    if not exists:
        db.add(NotInterested(user_id=user_id, tmdb_id=tmdb_id))
        await db.commit()
    return {"ok": True}

@router.get("/{user_id}/not_interested")
async def list_hidden_for_user(
    user_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[int]:
    ids = (
        await db.execute(
            select(NotInterested.tmdb_id).where(NotInterested.user_id == user_id)
        )
    ).scalars().all()
    return [int(x) for x in ids if x is not None]

