# app/routes/compat_legacy.py
"""
Legacy-compatibility endpoints that mirror the original frontend's expectations.

They provide these routes (mounted under /api in main.py):

GET    /library/favorites?user_id=1
POST   /library/favorites            { "user_id": 1, "tmdb_id": 1396 }
DELETE /library/favorites            { "user_id": 1, "tmdb_id": 1396 }

GET    /ratings?user_id=1
POST   /ratings                      { "user_id": 1, "tmdb_id": 1396, "rating": 9, "title": "...", ... }

POST   /library/not_interested       { "user_id": 1, "tmdb_id": 1396 }

GET    /recs?limit=12[&user_id=1]

Note:
- These endpoints are deliberately more permissive (no auth dependency) to unblock the current web app.
  If you want to require auth, inject `require_user` and cross-check `user_id`.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_async_db
from app.db_models import Show, FavoriteTmdb, NotInterested
try:
    # Optional: ratings model may live here in your codebase
    from app.db_models import UserRating  # type: ignore
except Exception:
    UserRating = None  # type: ignore

# If you have a recommend_for_user function, we will import it.
try:
    from app.services.recs_engine import recommend_for_user
except Exception:  # pragma: no cover
    recommend_for_user = None  # type: ignore

router = APIRouter(prefix="", tags=["Legacy Compatibility"])


# ---------- pydantic payloads ----------

class FavoritePayload(BaseModel):
    user_id: int
    tmdb_id: int

class RatingPayload(BaseModel):
    user_id: int
    tmdb_id: int
    rating: float = Field(..., ge=0, le=10)
    title: Optional[str] = None
    seasons_completed: Optional[int] = None
    notes: Optional[str] = None


# ---------- helpers ----------

async def _get_fav_ids(db: AsyncSession, user_id: int) -> List[int]:
    q = select(FavoriteTmdb.tmdb_id).where(FavoriteTmdb.user_id == user_id)
    rows = (await db.execute(q)).scalars().all()
    return list(rows or [])


# ---------- favorites ----------

@router.get("/library/favorites")
async def legacy_list_favorites(
    user_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_async_db),
) -> List[int]:
    """Return bare list of TMDb ids for user's favorites."""
    try:
        return await _get_fav_ids(db, user_id)
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/library/favorites", status_code=status.HTTP_201_CREATED)
async def legacy_add_favorite(
    payload: FavoritePayload = Body(...),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    try:
        # Upsert-ish: ignore if already present
        q = select(FavoriteTmdb).where(
            FavoriteTmdb.user_id == payload.user_id,
            FavoriteTmdb.tmdb_id == payload.tmdb_id,
        )
        existing = (await db.execute(q)).scalars().first()
        if not existing:
            db.add(FavoriteTmdb(user_id=payload.user_id, tmdb_id=payload.tmdb_id))
            await db.commit()
        return {"ok": True}
    except Exception as e:  # pragma: no cover
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/library/favorites")
async def legacy_remove_favorite(
    payload: FavoritePayload = Body(...),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    try:
        q = (
            delete(FavoriteTmdb)
            .where(
                FavoriteTmdb.user_id == payload.user_id,
                FavoriteTmdb.tmdb_id == payload.tmdb_id,
            )
        )
        await db.execute(q)
        await db.commit()
        return {"ok": True}
    except Exception as e:  # pragma: no cover
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------- not interested ----------

@router.post("/library/not_interested", status_code=status.HTTP_201_CREATED)
async def legacy_mark_not_interested(
    payload: FavoritePayload = Body(...),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    try:
        q = select(NotInterested).where(
            NotInterested.user_id == payload.user_id,
            NotInterested.tmdb_id == payload.tmdb_id,
        )
        existing = (await db.execute(q)).scalars().first()
        if not existing:
            db.add(NotInterested(user_id=payload.user_id, tmdb_id=payload.tmdb_id))
            await db.commit()
        return {"ok": True}
    except Exception as e:  # pragma: no cover
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------- ratings ----------

@router.get("/ratings")
async def legacy_list_ratings(
    user_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict]:
    """
    Return ratings in the compact shape expected by the web app:
    [{ tmdb_id, rating, title?, seasons_completed?, notes? }]
    """
    if UserRating is None:
        # Keep legacy web happy with empty list instead of 404
        return []
    try:
        q = select(UserRating).where(UserRating.user_id == user_id).order_by(getattr(UserRating, "updated_at", None).desc() if hasattr(UserRating, "updated_at") else UserRating.tmdb_id)  # type: ignore
        items = (await db.execute(q)).scalars().all()
        out = []
        for r in items:
            out.append(
                {
                    "tmdb_id": int(r.tmdb_id),
                    "rating": float(r.rating),
                    "title": getattr(r, "title", None),
                    "seasons_completed": getattr(r, "seasons_completed", None),
                    "notes": getattr(r, "notes", None),
                }
            )
        return out
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ratings", status_code=status.HTTP_201_CREATED)
async def legacy_upsert_rating(
    payload: RatingPayload = Body(...),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    if UserRating is None:
        # Soft success to keep UI flowing
        return {"ok": True}
    try:
        q = select(UserRating).where(
            UserRating.user_id == payload.user_id,
            UserRating.tmdb_id == payload.tmdb_id,
        )
        row = (await db.execute(q)).scalars().first()
        if row:
            # Update existing
            row.rating = float(payload.rating)
            if payload.title is not None:
                row.title = payload.title
            row.seasons_completed = payload.seasons_completed
            row.notes = payload.notes
        else:
            row = UserRating(
                user_id=payload.user_id,
                tmdb_id=payload.tmdb_id,
                rating=float(payload.rating),
                title=payload.title,
                seasons_completed=payload.seasons_completed,
                notes=payload.notes,
            )
            db.add(row)
        await db.commit()
        return {"ok": True}
    except Exception as e:  # pragma: no cover
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------- recommendations ----------

@router.get("/recs")
async def legacy_get_recs(
    limit: int = Query(12, ge=1, le=100),
    user_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict]:
    """
    Return a list of recommendation items:
    [{ title, score, poster_url?, tmdb_id?, year?, show_id?, external_id? }]
    """
    if recommend_for_user is None:
        return []

    try:
        items = await recommend_for_user(db=db, user_id=user_id, top_n=limit)

        # Normalize fields for the current web UI
        out: List[dict] = []
        for it in items:
            # allow dict-like or object-like results
            title = getattr(it, "title", None) or (isinstance(it, dict) and it.get("title"))
            score = getattr(it, "score", None) or (isinstance(it, dict) and it.get("score")) or 0.0
            poster = getattr(it, "poster_url", None) or (isinstance(it, dict) and it.get("poster_url"))
            tmdb_id = getattr(it, "tmdb_id", None) or (isinstance(it, dict) and it.get("tmdb_id"))
            year = getattr(it, "year", None) or (isinstance(it, dict) and it.get("year"))
            show_id = getattr(it, "show_id", None) or (isinstance(it, dict) and it.get("show_id"))
            external_id = getattr(it, "external_id", None) or (isinstance(it, dict) and it.get("external_id"))
            out.append(
                {
                    "title": title or "Untitled",
                    "score": float(score),
                    "poster_url": poster,
                    "tmdb_id": tmdb_id if tmdb_id is None else int(tmdb_id),
                    "year": None if year is None else int(year),
                    "show_id": show_id if show_id is None else int(show_id),
                    "external_id": external_id,
                }
            )
        return out
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(e))
