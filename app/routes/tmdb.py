# app/routes/tmdb.py
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import Show

router = APIRouter(prefix="/tmdb", tags=["tmdb"])
log = logging.getLogger("tmdb")

TMDB_API_KEY = os.getenv("TMDB_API_KEY") or ""
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_W500 = "https://image.tmdb.org/t/p/w500"

# Optional Redis cache
REDIS_URL = os.getenv("REDIS_URL", "")
try:
    from redis.asyncio import from_url as redis_from_url  # type: ignore
except Exception:
    redis_from_url = None  # type: ignore


def _year_from_first_air_date(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s[:4])
    except Exception:
        return None


def _serialize_tmdb_item(item: dict) -> dict[str, Any]:
    """Fallback shape if DB upsert fails."""
    tmdb_id = int(item.get("id") or 0)
    poster_path = item.get("poster_path")
    return {
        "tmdb_id": tmdb_id,
        "show_id": tmdb_id,
        "external_id": tmdb_id,
        "title": item.get("name") or item.get("original_name"),
        "poster_path": poster_path,
        "poster_url": f"{TMDB_IMG_W500}{poster_path}" if poster_path else None,
        "overview": item.get("overview"),
        "first_air_date": item.get("first_air_date"),
        "vote_average": item.get("vote_average"),
    }


def _serialize_show_row(s: Show) -> dict[str, Any]:
    tmdb_id = int(getattr(s, "show_id", 0) or 0)

    poster_path = getattr(s, "poster_path", None)
    poster_url = getattr(s, "poster_url", None)
    if not poster_url and poster_path:
        poster_url = f"{TMDB_IMG_W500}{poster_path}"

    ext_val = getattr(s, "external_id", None)
    try:
        external_id = int(ext_val) if ext_val is not None else tmdb_id
    except Exception:
        external_id = tmdb_id

    year_val = getattr(s, "year", None)
    year = int(year_val) if year_val is not None else None

    return {
        "tmdb_id": tmdb_id,
        "show_id": tmdb_id,
        "external_id": external_id,
        "title": getattr(s, "title", None),
        "year": year,
        "poster_path": poster_path,
        "poster_url": poster_url,
    }


async def _get_or_create_show_from_tmdb_item(db: AsyncSession, item: dict) -> Show:
    tmdb_id = item.get("id")
    if not tmdb_id:
        raise ValueError("TMDb item missing id")
    tmdb_id = int(tmdb_id)

    title = item.get("name") or item.get("original_name") or "Untitled"
    year = _year_from_first_air_date(item.get("first_air_date"))
    poster_path = item.get("poster_path")

    ext_str = str(tmdb_id)

    # Prefer PK match (show_id). Also allow external_id match if you stored it as string.
    q = select(Show).where((Show.show_id == tmdb_id) | (Show.external_id == ext_str))
    existing = (await db.execute(q)).scalars().first()

    if existing:
        # Update only if fields exist on the model
        if hasattr(existing, "title") and getattr(existing, "title", None) != title:
            existing.title = title
        if year is not None and hasattr(existing, "year") and getattr(existing, "year", None) != year:
            existing.year = year
        if hasattr(existing, "poster_path") and getattr(existing, "poster_path", None) != poster_path:
            existing.poster_path = poster_path
        if hasattr(existing, "external_id") and getattr(existing, "external_id", None) != ext_str:
            existing.external_id = ext_str
        await db.flush()
        return existing

    # ✅ CRITICAL: set show_id (your schema uses this as PK)
    kwargs: dict[str, Any] = {"show_id": tmdb_id, "title": title, "external_id": ext_str}
    if year is not None and hasattr(Show, "year"):
        kwargs["year"] = year
    if hasattr(Show, "poster_path"):
        kwargs["poster_path"] = poster_path
    if hasattr(Show, "poster_url") and poster_path:
        kwargs["poster_url"] = f"{TMDB_IMG_W500}{poster_path}"

    new_show = Show(**kwargs)
    db.add(new_show)
    await db.flush()
    return new_show


@router.api_route("/search", methods=["GET", "HEAD"], summary="Search TMDb TV")
async def tmdb_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=50),
    page: int = Query(1, ge=1, le=1000),
    db: AsyncSession = Depends(get_async_db),
):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY not set on server")

    cache_key = f"tmdb:search:tv:{q.strip().lower()}:{page}:{limit}"
    redis = redis_from_url(REDIS_URL, decode_responses=True) if (redis_from_url and REDIS_URL) else None

    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            log.exception("Redis read failed")

    # Call TMDb
    params = {"api_key": TMDB_API_KEY, "query": q, "page": page, "include_adult": "false"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{TMDB_BASE}/search/tv", params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"TMDb error {r.status_code}: {r.text[:200]}")

    payload = r.json()
    items = (payload.get("results") or [])[:limit]

    out: list[dict[str, Any]] = []
    for it in items:
        try:
            s = await _get_or_create_show_from_tmdb_item(db, it)
            out.append(_serialize_show_row(s))
        except Exception:
            # Don’t silently swallow — log and return TMDb item instead
            log.exception("Upsert failed for tmdb_id=%s", it.get("id"))
            out.append(_serialize_tmdb_item(it))

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        log.exception("Commit failed during tmdb search")

    if redis:
        try:
            await redis.setex(cache_key, 600, json.dumps(out))  # 10 mins
        except Exception:
            log.exception("Redis write failed")

    return out


@router.get("/tv/{tmdb_id}", summary="TMDb TV details (pass-through)")
async def tmdb_tv_details(tmdb_id: int = Path(..., ge=1)):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY not set on server")

    params = {"api_key": TMDB_API_KEY}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}", params=params)

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="TMDb show not found")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"TMDb error {r.status_code}: {r.text[:200]}")

    return r.json()

@router.get("/tv/{tmdb_id}/videos", summary="TMDb TV videos (trailers, teasers)")
async def tmdb_tv_videos(tmdb_id: int = Path(..., ge=1)):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY not set on server")

    params = {"api_key": TMDB_API_KEY}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/videos", params=params)

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="TMDb videos not found")
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"TMDb error {r.status_code}: {r.text[:200]}",
        )

    return r.json()

    @router.get("/tv/{tmdb_id}/watch/providers", summary="TMDb TV watch providers (where to watch)")
    async def tmdb_tv_watch_providers(tmdb_id: int = Path(..., ge=1)):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY not set on server")

    params = {"api_key": TMDB_API_KEY}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/watch/providers", params=params)

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="TMDb providers not found")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"TMDb error {r.status_code}: {r.text[:200]}")

    return r.json()

