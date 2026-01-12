# app/routes/tmdb.py
from __future__ import annotations

import os
import json
from typing import Any, List, Optional, Set

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import Show, NotInterested  # add NotInterested for filtering

router = APIRouter(prefix="/tmdb", tags=["tmdb"])

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Redis (async, optional)
try:
    from redis.asyncio import from_url as redis_from_url  # type: ignore
except Exception:
    redis_from_url = None  # type: ignore


# ---------- helpers ----------

def _year_from_first_air_date(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s[:4])
    except Exception:
        return None

def _serialize_show(s: Show) -> dict[str, Any]:
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

async def _get_or_create_show_from_tmdb_item(db: AsyncSession, item: dict) -> Show:
    """
    Upsert Show by TMDb id into local catalogue.
    """
    tmdb_id = item.get("id")
    if not tmdb_id:
        raise ValueError("TMDB item missing 'id'")

    title = item.get("name") or item.get("original_name") or "Untitled"
    year = _year_from_first_air_date(item.get("first_air_date"))
    poster_path = item.get("poster_path")
    poster_url = f"{TMDB_IMG}{poster_path}" if poster_path else None
    ext_str = str(tmdb_id)

    q = select(Show).where(Show.external_id == ext_str)
    existing: Show | None = (await db.execute(q)).scalar_one_or_none()

    if existing:
        changed = False
        if existing.title != title:
            existing.title = title
            changed = True
        if year is not None and getattr(existing, "year", None) != year:
            existing.year = year
            changed = True
        if poster_url is not None and getattr(existing, "poster_url", None) != poster_url:
            existing.poster_url = poster_url
            changed = True
        if changed:
            await db.flush()
        return existing

    new_show = Show(title=title, year=year, poster_url=poster_url, external_id=ext_str)
    db.add(new_show)
    await db.flush()
    return new_show


# ---------- endpoints ----------

@router.get("/search", summary="Search TMDb (cached) and upsert results into local Show table")
async def search_tmdb(
    q: str = Query(min_length=2, description="Search term (min 2 chars)"),
    page: int = Query(1, ge=1, le=1000),
    limit: int = Query(20, ge=1, le=50),
    # New: optional per-user filtering of not_interested
    user_id: Optional[int] = Query(default=None, ge=1, description="If provided, exclude user's hidden shows"),
    exclude_hidden: bool = Query(True, description="When user_id is provided, hide not_interested results"),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict[str, Any]]:
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY not configured")

    # Cache is only for the raw TMDb-based result set (not user-filtered)
    cache_key = f"tmdb:search:q={q}:page={page}:limit={limit}"
    redis = redis_from_url(REDIS_URL, decode_responses=True) if redis_from_url else None
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                base_out: List[dict[str, Any]] = json.loads(cached)
                # Apply per-user filter on top of cached results (no per-user key explosion)
                if user_id and exclude_hidden:
                    hidden: Set[int] = set(
                        int(x) for x in (
                            await db.execute(
                                select(NotInterested.tmdb_id).where(NotInterested.user_id == user_id)
                            )
                        ).scalars().all()
                        if x is not None
                    )
                    return [it for it in base_out if int(it.get("external_id") or 0) not in hidden]
                return base_out
        except Exception:
            pass  # non-fatal

    params = {"api_key": TMDB_API_KEY, "query": q, "page": page, "include_adult": "false"}
    url = f"{TMDB_BASE}/search/tv"

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=f"TMDB search failed: {r.text}")

    payload = r.json()
    items = (payload or {}).get("results", [])[:limit]

    results: list[Show] = []
    for it in items:
        try:
            s = await _get_or_create_show_from_tmdb_item(db, it)
            results.append(s)
        except Exception:
            continue

    await db.commit()

    base_out = [_serialize_show(s) for s in results]
    if redis:
        try:
            await redis.setex(cache_key, 86400, json.dumps(base_out))
        except Exception:
            pass

    # Apply per-user hide after caching
    if user_id and exclude_hidden:
        hidden: Set[int] = set(
            int(x) for x in (
                await db.execute(
                    select(NotInterested.tmdb_id).where(NotInterested.user_id == user_id)
                )
            ).scalars().all()
            if x is not None
        )
        return [it for it in base_out if int(it.get("external_id") or 0) not in hidden]

    return base_out


@router.get("/tv/{tmdb_id}", summary="TMDb TV details (cached pass-through)")
async def tv_details(
    tmdb_id: int = Path(ge=1),
):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY not configured")

    cache_key = f"tmdb:tv:{tmdb_id}:details"
    redis = redis_from_url(REDIS_URL, decode_responses=True) if redis_from_url else None
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    url = f"{TMDB_BASE}/tv/{tmdb_id}"
    params = {"api_key": TMDB_API_KEY}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="TMDb show not found")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=f"TMDb details failed: {r.text}")

    data = r.json()
    if redis:
        try:
            await redis.setex(cache_key, 86400, json.dumps(data))
        except Exception:
            pass
    return data
