from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

# Prefer the project’s current dependency locations; fall back if names differ
try:
    from app.db.async_session import get_async_db  # type: ignore
except Exception:  # pragma: no cover
    from app.database import get_async_db  # type: ignore

try:
    from app.auth.dependencies import require_user  # type: ignore
except Exception:  # pragma: no cover
    from app.security import require_user  # type: ignore

from app.db_models import FavoriteTmdb, Show

router = APIRouter(prefix="/users", tags=["Users"])


def _poster_url(poster_path: Optional[str]) -> Optional[str]:
    return f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None


def _serialize_show(s: Show) -> Dict[str, Any]:
    poster_path = getattr(s, "poster_path", None)
    poster_url = getattr(s, "poster_url", None) or _poster_url(poster_path)
    year = getattr(s, "year", None)
    return {
        "tmdb_id": int(getattr(s, "show_id")),
        "show_id": int(getattr(s, "show_id")),
        "title": getattr(s, "title", None),
        "year": int(year) if year is not None else None,
        "poster_path": poster_path,
        "poster_url": poster_url,
    }


async def _tmdb_tv_details(tmdb_id: int) -> Optional[dict]:
    """Minimal TMDb TV details fetch for backfilling shows.
    Supports either TMDB_API_KEY (v3) or TMDB_BEARER_TOKEN / TMDB_READ_ACCESS_TOKEN / TMDB_ACCESS_TOKEN (v4).
    """
    import os
    import httpx

    api_key = os.getenv("TMDB_API_KEY")
    bearer = (
        os.getenv("TMDB_BEARER_TOKEN")
        or os.getenv("TMDB_READ_ACCESS_TOKEN")
        or os.getenv("TMDB_ACCESS_TOKEN")
    )

    if not api_key and not bearer:
        return None

    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
    headers: Dict[str, str] = {}
    params: Dict[str, str] = {}

    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    else:
        params["api_key"] = api_key  # type: ignore

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers, params=params)
        if r.status_code != 200:
            return None
        return r.json()


async def _ensure_show(db: AsyncSession, tmdb_id: int) -> Optional[Show]:
    show = (await db.execute(select(Show).where(Show.show_id == tmdb_id))).scalar_one_or_none()
    if show:
        return show

    data = await _tmdb_tv_details(tmdb_id)
    if not data:
        return None

    title = data.get("name") or data.get("title") or f"TMDb #{tmdb_id}"
    first_air = data.get("first_air_date") or ""
    year = int(first_air[:4]) if len(first_air) >= 4 and first_air[:4].isdigit() else None
    poster_path = data.get("poster_path")

    show = Show(
        show_id=int(tmdb_id),
        title=title,
        poster_path=poster_path,
        year=year,
        external_id=int(tmdb_id),
    )
    db.add(show)
    await db.commit()
    await db.refresh(show)
    return show


@router.get("/{user_id}/favorites")
async def list_favorites(
    user_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    favs = (
        await db.execute(select(FavoriteTmdb.tmdb_id).where(FavoriteTmdb.user_id == user_id))
    ).scalars().all()

    out: List[Dict[str, Any]] = []
    for tmdb_id in favs:
        show = await _ensure_show(db, int(tmdb_id))
        if show:
            out.append(_serialize_show(show))
        else:
            out.append(
                {
                    "tmdb_id": int(tmdb_id),
                    "show_id": int(tmdb_id),
                    "title": f"TMDb #{int(tmdb_id)}",
                    "year": None,
                    "poster_path": None,
                    "poster_url": None,
                }
            )
    return out


@router.post("/{user_id}/favorites/{tmdb_id}")
async def add_favorite(
    user_id: int = Path(..., ge=1),
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
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


@router.delete("/{user_id}/favorites/{tmdb_id}")
async def remove_favorite(
    user_id: int = Path(..., ge=1),
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
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
