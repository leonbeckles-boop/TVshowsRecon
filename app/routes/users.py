# app/routes/users.py
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import FavoriteTmdb, Show, NotInterested
from app.security import require_user, require_user_match

router = APIRouter(prefix="/users", tags=["Users"])


def _serialize_show(s: Show) -> dict[str, Any]:
    ext: Optional[int] = None
    if s.external_id is not None:
        try:
            ext = int(s.external_id)
        except Exception:
            ext = None

    return {
        "show_id": int(s.show_id),
        "title": s.title,
        "year": int(s.year) if getattr(s, "year", None) is not None else None,
        # DB column is poster_path (not poster_url)
        "poster_path": getattr(s, "poster_path", None),
        "external_id": ext,
    }


@router.get("/{user_id}/favorites")
async def list_favorites(
    user_id: int,
    _: Any = Depends(require_user_match),  # enforce ownership via JWT
    db: AsyncSession = Depends(get_async_db),
) -> List[dict[str, Any]]:
    fav_rows = (
        (await db.execute(select(FavoriteTmdb).where(FavoriteTmdb.user_id == user_id)))
        .scalars()
        .all()
    )

    tmdb_ids = [fr.tmdb_id for fr in fav_rows]
    if not tmdb_ids:
        return []

    # Show.external_id is stored as STRING in DB
    ext_ids = [str(i) for i in tmdb_ids]
    shows = (
        (await db.execute(select(Show).where(Show.external_id.in_(ext_ids))))
        .scalars()
        .all()
    )
    return [_serialize_show(s) for s in shows]


@router.post("/{user_id}/favorites/{tmdb_id}")
async def add_favorite(
    user_id: int,
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user_match),
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
    _: Any = Depends(require_user_match),
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
    user_id: int = Path(..., ge=1),
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user_match),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    exists = (
        await db.execute(
            select(NotInterested).where(
                and_(NotInterested.user_id == user_id, NotInterested.tmdb_id == tmdb_id)
            )
        )
    ).scalar_one_or_none()

    if not exists:
        db.add(NotInterested(user_id=user_id, tmdb_id=tmdb_id))
        await db.commit()

    return {"ok": True}


@router.get("/{user_id}/not_interested")
async def list_hidden_for_user(
    user_id: int = Path(..., ge=1),
    _: Any = Depends(require_user_match),
    db: AsyncSession = Depends(get_async_db),
) -> List[int]:
    ids = (
        await db.execute(select(NotInterested.tmdb_id).where(NotInterested.user_id == user_id))
    ).scalars().all()
    return [int(x) for x in ids if x is not None]
