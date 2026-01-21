
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import FavoriteTmdb, Show, NotInterested
from app.security import require_user
from app.services.tmdb import fetch_tv_details  # <-- existing TMDB helper

router = APIRouter(prefix="/users", tags=["Users"])


def _serialize_show(s: Show) -> dict[str, Any]:
    return {
        "tmdb_id": int(s.external_id) if s.external_id else int(s.show_id),
        "show_id": int(s.show_id),
        "title": s.title,
        "year": int(s.year) if s.year is not None else None,
        "poster_path": s.poster_path,
        "poster_url": s.poster_url,
    }


async def _ensure_show(db: AsyncSession, tmdb_id: int) -> Optional[Show]:
    res = await db.execute(select(Show).where(Show.external_id == str(tmdb_id)))
    show = res.scalar_one_or_none()
    if show:
        return show

    data = await fetch_tv_details(tmdb_id)
    if not data:
        return None

    show = Show(
        show_id=tmdb_id,
        external_id=str(tmdb_id),
        title=data.get("name") or data.get("title") or f"TMDb #{tmdb_id}",
        year=int(data.get("first_air_date", "0000")[:4]) if data.get("first_air_date") else None,
        poster_path=data.get("poster_path"),
        poster_url=(
            f"https://image.tmdb.org/t/p/w500{data['poster_path']}"
            if data.get("poster_path")
            else None
        ),
    )
    db.add(show)
    await db.commit()
    await db.refresh(show)
    return show


@router.get("users/{user_id}/favorites")
async def list_favorites(
    user_id: int,
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict[str, Any]]:
    favs = (await db.execute(
        select(FavoriteTmdb.tmdb_id).where(FavoriteTmdb.user_id == user_id)
    )).scalars().all()

    out: List[dict[str, Any]] = []
    for tmdb_id in favs:
        show = await _ensure_show(db, tmdb_id)
        if show:
            out.append(_serialize_show(show))
    return out


@router.post("users/{user_id}/favorites/{tmdb_id}")
async def add_favorite(
    user_id: int,
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    exists = (
        await db.execute(
            select(FavoriteTmdb).where(
                and_(FavoriteTmdb.user_id == user_id, FavoriteTmdb.tmdb_id == tmdb_id)
            )
        )
    ).scalar_one_or_none()

    if not exists:
        db.add(FavoriteTmdb(user_id=user_id, tmdb_id=tmdb_id))
        await _ensure_show(db, tmdb_id)
        await db.commit()

    return {"ok": True}


@router.delete("users/{user_id}/favorites/{tmdb_id}")
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
