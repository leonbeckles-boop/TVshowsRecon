# app/routes/tmdb.py
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Show


try:
    # redis-py 4.x (async)
    from redis.asyncio import Redis
    from redis.asyncio import from_url as redis_from_url
except Exception:
    Redis = None  # type: ignore
    redis_from_url = None  # type: ignore

router = APIRouter(prefix="/tmdb", tags=["tmdb"])
logger = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_W500 = "https://image.tmdb.org/t/p/w500"

TMDB_API_KEY = os.getenv("TMDB_API_KEY") or ""
REDIS_URL = os.getenv("REDIS_URL") or ""

# ---------- helpers ----------


def _year_from_first_air_date(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s[:4])
    except Exception:
        return None


def _serialize_show_row(s: Show) -> dict[str, Any]:
    """Frontend-friendly show dict (includes legacy + modern keys)."""
    tmdb_id = int(getattr(s, "show_id", 0) or 0)
    poster_path = getattr(s, "poster_path", None)

    ext_val = getattr(s, "external_id", None)
    try:
        external_id = int(ext_val) if ext_val is not None else tmdb_id
    except Exception:
        external_id = tmdb_id

    year_val = getattr(s, "year", None)
    year = int(year_val) if year_val is not None else None

    poster_url = getattr(s, "poster_url", None)
    if not poster_url and poster_path:
        poster_url = f"{TMDB_IMG_W500}{poster_path}"

    return {
        "tmdb_id": tmdb_id,
        "show_id": tmdb_id,  # legacy
        "external_id": external_id,
        "title": getattr(s, "title", None),
        "year": year,
        "poster_path": poster_path,
        "poster_url": poster_url,
    }


def _serialize_tmdb_item(item: dict) -> dict[str, Any]:
    """Serialize raw TMDb search item into UI-friendly shape."""
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
        "vote_average": item.get("vote_average"),
        "first_air_date": item.get("first_air_date"),
    }


async def _get_or_create_show_from_tmdb_item(db: AsyncSession, item: dict) -> Show:
    """
    Upsert Show by TMDb id into local catalogue.

    IMPORTANT: `shows.show_id` is the TMDb id (PK). Always set it.
    """
    tmdb_id = item.get("id")
    if not tmdb_id:
        raise ValueError("TMDB item missing 'id'")

    tmdb_id_int = int(tmdb_id)
    title = item.get("name") or item.get("original_name") or "Untitled"
    year = _year_from_first_air_date(item.get("first_air_date"))
    poster_path = item.get("poster_path")
    ext_str = str(tmdb_id_int)

    q = select(Show).where((Show.show_id == tmdb_id_int) | (Show.external_id == ext_str))
    existing = (await db.execute(q)).scalars().first()

    def _maybe_set(obj: Any, attr: str, value: Any) -> bool:
        if not hasattr(obj, attr):
            return False
        cur = getattr(obj, attr, None)
        if value is not None and cur != value:
            setattr(obj, attr, value)
            return True
        return False

    if existing:
        changed = False
        changed |= _maybe_set(existing, "title", title)
        changed |= _maybe_set(existing, "year", year)
        changed |= _maybe_set(existing, "poster_path", poster_path)
        changed |= _maybe_set(existing, "external_id", ext_str)
        if changed:
            await db.flush()
        return existing

    kwargs: dict[str, Any] = {
        "show_id": tmdb_id_int,          # ✅ critical fix
        "title": title,
        "external_id": ext_str,
    }
    if year is not None and hasattr(Show, "year"):
        kwargs["year"] = year
    if hasattr(Show, "poster_path"):
        kwargs["poster_path"] = poster_path

    new_show = Show(**kwargs)
    db.add(new_show)
    await db.flush()
    return new_show


def _cache_key_search(q: str, limit: int) -> str:
    qn = (q or "").strip().lower()
    return f"tmdb:search:tv:{qn}:{limit}"


async def _get_redis():
    if not redis_from_url or not REDIS_URL:
        return None
    try:
        return redis_from_url(REDIS_URL, decode_responses=True)
    except Exception:
        logger.exception("Failed to init Redis client")
        return None


# ---------- endpoints ----------

@router.head("/search", include_in_schema=False)
async def tmdb_search_head() -> None:
    return None


@router.get("/search")
async def tmdb_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Search TMDb TV shows. Returns a list of show-like objects.

    We attempt to upsert into the local `shows` table. If DB writes fail,
    we still return raw TMDb results (and log the error).
    """
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY is not set on the server")

    redis = await _get_redis()
    cache_key = _cache_key_search(q, limit)

    # Cache read
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            logger.exception("Redis read failed for %s", cache_key)

    url = f"{TMDB_BASE}/search/tv"
    params = {"api_key": TMDB_API_KEY, "query": q, "include_adult": "false"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        payload = r.json()

    items = (payload.get("results") or [])[:limit]

    results: list[Show] = []
    fallback: list[dict[str, Any]] = []

    for it in items:
        try:
            s = await _get_or_create_show_from_tmdb_item(db, it)
            results.append(s)
        except Exception:
            # ✅ never silently swallow — log and still return TMDb data
            logger.exception("TMDb search upsert failed for id=%s name=%s", it.get("id"), it.get("name"))
            fallback.append(_serialize_tmdb_item(it))

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("DB commit failed during TMDb search")

    out = [_serialize_show_row(s) for s in results] + fallback

    # Cache write
    if redis:
        try:
            await redis.set(cache_key, json.dumps(out), ex=60 * 10)  # 10 min
        except Exception:
            logger.exception("Redis write failed for %s", cache_key)

    return out


@router.get("/tv/{tmdb_id}")
async def tmdb_tv_details(
    tmdb_id: int = Path(..., ge=1),
):
    """Proxy TMDb TV details (no DB write)."""
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY is not set on the server")

    url = f"{TMDB_BASE}/tv/{tmdb_id}"
    params = {"api_key": TMDB_API_KEY}

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()
