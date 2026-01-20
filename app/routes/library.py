# app/routes/library.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Path, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, delete, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert  # PG UPSERT

from app.database import get_async_db
from app.db_models import UserRating, FavoriteTmdb, NotInterested, Show
from app.security import require_user

router = APIRouter(prefix="/library", tags=["library"])

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _serialize_show(s: Show) -> Dict[str, Any]:
    ext_num: Optional[int] = None
    ext_val = getattr(s, "external_id", None)
    if ext_val is not None:
        try:
            ext_num = int(ext_val)
        except Exception:
            ext_num = None

    return {
        "show_id": int(s.show_id),
        "title": s.title,
        "year": int(s.year) if getattr(s, "year", None) is not None else None,
        "poster_url": getattr(s, "poster_url", None),
        "external_id": ext_num,
    }

# ──────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────

class RatingOut(BaseModel):
    tmdb_id: int
    rating: float
    title: Optional[str] = None
    seasons_completed: Optional[int] = None
    notes: Optional[str] = None

class RatingsResponse(BaseModel):
    user_id: int
    ratings: List[RatingOut]

class RatingIn(BaseModel):
    tmdb_id: int = Field(ge=1)
    rating: float = Field(ge=0, le=10)
    title: Optional[str] = None
    seasons_completed: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None

class RatingBody(RatingIn):
    user_id: int = Field(ge=1)

class FavoriteBody(BaseModel):
    user_id: int = Field(ge=1)
    tmdb_id: int = Field(ge=1)

# ──────────────────────────────────────────────────────────────────────
# Ratings (path style preferred)
# ──────────────────────────────────────────────────────────────────────

@router.get("/{user_id}/ratings", response_model=RatingsResponse)
async def list_ratings_for_user(
    user_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
):
    rows = (await db.execute(
        select(UserRating).where(UserRating.user_id == user_id)
    )).scalars().all()
    return {
        "user_id": user_id,
        "ratings": [
            {
                "tmdb_id": r.tmdb_id,
                "rating": float(r.rating),
                "title": r.title,
                "seasons_completed": r.seasons_completed,
                "notes": r.notes,
            }
            for r in rows
        ],
    }

@router.post("/{user_id}/ratings")
async def upsert_rating_path(
    user_id: int = Path(ge=1),
    payload: RatingIn = Body(...),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
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

# ──────────────────────────────────────────────────────────────────────
# Ratings (compat: query/body style)
# ──────────────────────────────────────────────────────────────────────

@router.get("/ratings", response_model=RatingsResponse)
async def list_ratings_query(
    user_id: int = Query(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await list_ratings_for_user(user_id, _, db)  # reuse

@router.post("/ratings")
async def upsert_rating_body(
    payload: RatingBody,
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    return await upsert_rating_path(payload.user_id, payload, _, db)

# ──────────────────────────────────────────────────────────────────────
# Favorites (user-scoped, path style; idempotent + distinct, now with tmdb_id)
# ──────────────────────────────────────────────────────────────────────

@router.get("/{user_id}/favorites")
async def list_favorites_for_user(
    user_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict]:
    # Unique tmdb ids first (avoid join dupes)
    fav_ids = (
        await db.execute(
            select(distinct(FavoriteTmdb.tmdb_id)).where(FavoriteTmdb.user_id == user_id)
        )
    ).scalars().all()

    # Normalize + drop nulls
    fav_ids = [int(x) for x in fav_ids if x is not None]

    if not fav_ids:
        return []

    # ✅ Enrich using Show.show_id (TMDb id / PK in your schema)
    shows: List[Show] = (
        await db.execute(select(Show).where(Show.show_id.in_(fav_ids)))
    ).scalars().all()

    by_id = {int(s.show_id): s for s in shows}

    out: List[dict] = []
    for tmdb_id in fav_ids:
        s = by_id.get(int(tmdb_id))
        if s:
            poster_path = getattr(s, "poster_path", None)
            poster_url = getattr(s, "poster_url", None)
            if not poster_url and poster_path:
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"

            out.append(
                {
                    "tmdb_id": int(tmdb_id),
                    "show_id": int(s.show_id),
                    "title": getattr(s, "title", None),
                    "year": int(getattr(s, "year", 0)) if getattr(s, "year", None) is not None else None,
                    "poster_path": poster_path,
                    "poster_url": poster_url,
                }
            )
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
async def add_favorite_path(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    # Dialect-aware UPSERT (ON CONFLICT DO NOTHING) via ORM table — avoids hardcoding table name.
    ins = pg_insert(FavoriteTmdb.__table__).values(
        user_id=user_id,
        tmdb_id=tmdb_id,
    ).on_conflict_do_nothing(
        index_elements=["user_id", "tmdb_id"]
    )
    await db.execute(ins)
    await db.commit()
    return {"ok": True}

@router.delete("/{user_id}/favorites/{tmdb_id}")
async def remove_favorite_path(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    await db.execute(
        delete(FavoriteTmdb).where(
            and_(FavoriteTmdb.user_id == user_id, FavoriteTmdb.tmdb_id == tmdb_id)
        )
    )
    await db.commit()
    return {"ok": True}

# ──────────────────────────────────────────────────────────────────────
# Not Interested (hide/list)
# ──────────────────────────────────────────────────────────────────────

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
