from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path
from sqlalchemy import text
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


router = APIRouter(prefix="/users", tags=["Users"])


def _poster_url(poster_path: Optional[str]) -> Optional[str]:
    return f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None


async def _tmdb_tv_details(tmdb_id: int) -> Optional[dict]:
    """Minimal TMDb TV details fetch (NO DB writes).

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


async def _fetch_show_from_db(db: AsyncSession, tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Fetch show metadata from local DB if present (schema uses shows.show_id as TMDb id)."""
    row = (
        await db.execute(
            text(
                """
                SELECT show_id, title, poster_path, year
                FROM shows
                WHERE show_id = :sid
                """
            ),
            {"sid": tmdb_id},
        )
    ).mappings().first()

    if not row:
        return None

    poster_path = row.get("poster_path")
    return {
        "tmdb_id": int(row["show_id"]),
        "show_id": int(row["show_id"]),
        "title": row.get("title") or f"TMDb #{tmdb_id}",
        "year": int(row["year"]) if row.get("year") is not None else None,
        "poster_path": poster_path,
        "poster_url": _poster_url(poster_path),
    }


async def _resolve_show_payload(db: AsyncSession, tmdb_id: int) -> Dict[str, Any]:
    """Return best-effort show payload:
    1) local DB shows table
    2) TMDb API (no DB writes)
    3) fallback placeholder
    """
    db_payload = await _fetch_show_from_db(db, tmdb_id)
    if db_payload:
        return db_payload

    data = await _tmdb_tv_details(tmdb_id)
    if data:
        title = data.get("name") or data.get("title") or f"TMDb #{tmdb_id}"
        first_air = data.get("first_air_date") or ""
        year = int(first_air[:4]) if len(first_air) >= 4 and first_air[:4].isdigit() else None
        poster_path = data.get("poster_path")
        return {
            "tmdb_id": tmdb_id,
            "show_id": tmdb_id,
            "title": title,
            "year": year,
            "poster_path": poster_path,
            "poster_url": _poster_url(poster_path),
        }

    return {
        "tmdb_id": tmdb_id,
        "show_id": tmdb_id,
        "title": f"TMDb #{tmdb_id}",
        "year": None,
        "poster_path": None,
        "poster_url": None,
    }


@router.get("/{user_id}/favorites")
async def list_favorites(
    user_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    # Canonical table is user_favorites(user_id, tmdb_id)
    tmdb_ids = (
        await db.execute(
            text(
                """
                SELECT tmdb_id
                FROM user_favorites
                WHERE user_id = :uid
                ORDER BY id DESC NULLS LAST
                """
            ),
            {"uid": user_id},
        )
    ).scalars().all()

    out: List[Dict[str, Any]] = []
    for tid in tmdb_ids:
        out.append(await _resolve_show_payload(db, int(tid)))
    return out


@router.post("/{user_id}/favorites/{tmdb_id}")
async def add_favorite(
    user_id: int = Path(..., ge=1),
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    # Unique(user_id, tmdb_id) exists per your schema; ON CONFLICT keeps this idempotent.
    await db.execute(
        text(
            """
            INSERT INTO user_favorites (user_id, tmdb_id)
            VALUES (:uid, :tid)
            ON CONFLICT (user_id, tmdb_id) DO NOTHING
            """
        ),
        {"uid": user_id, "tid": tmdb_id},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/{user_id}/favorites/{tmdb_id}")
async def remove_favorite(
    user_id: int = Path(..., ge=1),
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    await db.execute(
        text(
            """
            DELETE FROM user_favorites
            WHERE user_id = :uid AND tmdb_id = :tid
            """
        ),
        {"uid": user_id, "tid": tmdb_id},
    )
    await db.commit()
    return {"ok": True}
