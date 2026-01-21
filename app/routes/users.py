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


def _poster_url_from_path(poster_path: Optional[str]) -> Optional[str]:
    # If value already looks like a URL, keep it.
    if not poster_path:
        return None
    if poster_path.startswith("http://") or poster_path.startswith("https://"):
        return poster_path
    # TMDb poster paths usually start with "/"
    if not poster_path.startswith("/"):
        poster_path = "/" + poster_path
    return f"https://image.tmdb.org/t/p/w500{poster_path}"


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


async def _try_show_query(db: AsyncSession, sql: str, params: dict) -> Optional[Dict[str, Any]]:
    """Run a query variant; return first row mapping or None. Swallows 'missing column' errors."""
    try:
        return (await db.execute(text(sql), params)).mappings().first()
    except Exception:
        # Most common here: asyncpg UndefinedColumnError surfaced through SQLAlchemy
        return None


async def _fetch_show_from_db(db: AsyncSession, tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Fetch show metadata from local DB.

    NOTE: Your production DB currently errors on 'poster_path' missing, so we try multiple
    column variants to stay compatible with whichever schema is deployed.
    """
    variants = [
        # Most common
        "SELECT show_id, title, poster_path AS poster, year FROM shows WHERE show_id = :sid",
        # Alternate poster column
        "SELECT show_id, title, poster AS poster, year FROM shows WHERE show_id = :sid",
        # Some schemas store full URL
        "SELECT show_id, title, poster_url AS poster, year FROM shows WHERE show_id = :sid",
        # Year sometimes named release_year
        "SELECT show_id, title, poster_path AS poster, release_year AS year FROM shows WHERE show_id = :sid",
        "SELECT show_id, title, poster AS poster, release_year AS year FROM shows WHERE show_id = :sid",
        "SELECT show_id, title, poster_url AS poster, release_year AS year FROM shows WHERE show_id = :sid",
    ]

    row: Optional[Dict[str, Any]] = None
    for sql in variants:
        row = await _try_show_query(db, sql, {"sid": tmdb_id})
        if row:
            break

    if not row:
        return None

    poster_val = row.get("poster")
    year_val = row.get("year")

    # year can be int, string, date; try best-effort
    year: Optional[int] = None
    if year_val is not None:
        s = str(year_val)
        if len(s) >= 4 and s[:4].isdigit():
            year = int(s[:4])

    return {
        "tmdb_id": int(row.get("show_id") or tmdb_id),
        "show_id": int(row.get("show_id") or tmdb_id),
        "title": row.get("title") or f"TMDb #{tmdb_id}",
        "year": year,
        "poster_path": str(poster_val) if poster_val and not str(poster_val).startswith("http") else None,
        "poster_url": _poster_url_from_path(str(poster_val)) if poster_val else None,
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
            "poster_url": _poster_url_from_path(poster_path) if poster_path else None,
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
