# app/routes/users.py
from __future__ import annotations

import os
from typing import Any, List, Optional

import httpx
from fastapi import APIRouter, Depends, Path
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import FavoriteTmdb, NotInterested, Show
from app.security import require_user_match

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
TMDB_KEY = os.getenv("TMDB_API_KEY") or os.getenv("TMDB_KEY")

router = APIRouter(prefix="/users", tags=["Users"])


async def _tmdb_details_min(tmdb_id: int) -> dict[str, Any]:
    """
    Minimal TMDb enrichment for favorites when our shows table is missing fields.
    Returns: {title, year, poster_path}
    """
    if not TMDB_KEY:
        return {}

    url = f"{TMDB_API}/tv/{tmdb_id}?api_key={TMDB_KEY}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return {}
        data = r.json() or {}
        first_air = data.get("first_air_date") or ""
        year = None
        if isinstance(first_air, str) and len(first_air) >= 4:
            try:
                year = int(first_air[:4])
            except Exception:
                year = None

        return {
            "title": data.get("name") or data.get("original_name"),
            "year": year,
            "poster_path": data.get("poster_path"),
        }
    except Exception:
        return {}


def _serialize_show(s: Show) -> dict[str, Any]:
    poster_path = getattr(s, "poster_path", None)
    poster_url = f"{TMDB_IMG}{poster_path}" if poster_path else None

    ext: Optional[int] = None
    if getattr(s, "external_id", None) is not None:
        try:
            ext = int(s.external_id)
        except Exception:
            ext = None

    return {
        "show_id": int(s.show_id),
        "title": s.title,
        "year": int(s.year) if getattr(s, "year", None) is not None else None,
        "poster_path": poster_path,
        "poster_url": poster_url,
        "external_id": ext,
    }


@router.get("/{user_id}/favorites")
async def list_favorites(
    user_id: int,
    _: Any = Depends(require_user_match),  # enforce ownership via JWT
    db: AsyncSession = Depends(get_async_db),
) -> List[dict[str, Any]]:
    # Pull favorites in a stable order
    fav_rows = (
        (await db.execute(
            select(FavoriteTmdb)
            .where(FavoriteTmdb.user_id == user_id)
            .order_by(FavoriteTmdb.id.asc())
        ))
        .scalars()
        .all()
    )

    tmdb_ids = [int(fr.tmdb_id) for fr in fav_rows if fr.tmdb_id is not None]
    if not tmdb_ids:
        return []

    # Fetch any Show rows we have for those tmdb ids
    shows = (
        (await db.execute(select(Show).where(Show.show_id.in_(tmdb_ids))))
        .scalars()
        .all()
    )
    show_by_id = {int(s.show_id): s for s in shows}

    out: list[dict[str, Any]] = []

    # Build response in the same order as favorites
    for tid in tmdb_ids:
        s = show_by_id.get(int(tid))
        if s:
            item = _serialize_show(s)

            # If DB is missing poster/title/year, enrich from TMDb (minimal call)
            if (not item.get("poster_path")) or (not item.get("title")) or (item.get("year") is None):
                extra = await _tmdb_details_min(int(tid))
                if extra:
                    item["poster_path"] = item.get("poster_path") or extra.get("poster_path")
                    if not item.get("poster_url") and item.get("poster_path"):
                        item["poster_url"] = f"{TMDB_IMG}{item['poster_path']}"
                    item["title"] = item.get("title") or extra.get("title")
                    if item.get("year") is None:
                        item["year"] = extra.get("year")

            out.append(item)
        else:
            # No Show row in DB -> still return something usable
            extra = await _tmdb_details_min(int(tid))
            poster_path = extra.get("poster_path") if extra else None
            out.append(
                {
                    "show_id": int(tid),
                    "title": extra.get("title") if extra else None,
                    "year": extra.get("year") if extra else None,
                    "poster_path": poster_path,
                    "poster_url": f"{TMDB_IMG}{poster_path}" if poster_path else None,
                    "external_id": int(tid),
                }
            )

    return out


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
