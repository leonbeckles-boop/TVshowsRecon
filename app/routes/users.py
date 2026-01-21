# app/routes/users.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.security import require_user

router = APIRouter(prefix="/users", tags=["Users"])


def _poster_url(poster_path: Optional[str]) -> Optional[str]:
    if not poster_path:
        return None
    # TMDb poster paths usually already include leading '/'
    return f"https://image.tmdb.org/t/p/w500{poster_path}"


@router.get("/{user_id}/favorites", summary="List Favorites")
async def list_favorites(
    user_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    # 1) get tmdb ids from user_favorites
    fav_ids = (
        await db.execute(
            text(
                """
                SELECT tmdb_id
                FROM user_favorites
                WHERE user_id = :uid
                ORDER BY id DESC
                """
            ),
            {"uid": user_id},
        )
    ).scalars().all()

    ids: List[int] = [int(x) for x in fav_ids if x is not None]
    if not ids:
        return []

    # 2) hydrate from shows table (if present)
    q = text(
        """
        SELECT show_id, title, poster_path, first_air_date
        FROM shows
        WHERE show_id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))

    rows = (await db.execute(q, {"ids": ids})).mappings().all()
    by_id: Dict[int, Dict[str, Any]] = {int(r["show_id"]): dict(r) for r in rows if r.get("show_id") is not None}

    out: List[Dict[str, Any]] = []
    for tid in ids:
        row = by_id.get(int(tid))
        title = row.get("title") if row else None
        poster_path = row.get("poster_path") if row else None
        first_air_date = row.get("first_air_date") if row else None

        year: Optional[int] = None
        if first_air_date:
            try:
                year = int(str(first_air_date)[:4])
            except Exception:
                year = None

        out.append(
            {
                "tmdb_id": int(tid),
                "show_id": int(tid),
                "title": title or f"TMDb #{tid}",
                "year": year,
                "poster_path": poster_path,
                "poster_url": _poster_url(poster_path),
            }
        )

    return out


@router.post(
    "/{user_id}/favorites/{tmdb_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Add Favorite",
)
async def add_favorite(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
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
    return {"ok": True, "user_id": user_id, "tmdb_id": tmdb_id}


@router.delete(
    "/{user_id}/favorites/{tmdb_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove Favorite",
)
async def remove_favorite(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
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
    return {"ok": True, "user_id": user_id, "tmdb_id": tmdb_id}


@router.post(
    "/{user_id}/not_interested/{tmdb_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Hide Show Path",
)
async def add_not_interested(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    # not_interested doesn't necessarily have a unique constraint; avoid duplicates safely.
    await db.execute(
        text(
            """
            INSERT INTO not_interested (user_id, tmdb_id)
            SELECT :uid, :tid
            WHERE NOT EXISTS (
                SELECT 1 FROM not_interested WHERE user_id = :uid AND tmdb_id = :tid
            )
            """
        ),
        {"uid": user_id, "tid": tmdb_id},
    )
    await db.commit()
    return {"ok": True, "user_id": user_id, "tmdb_id": tmdb_id}


@router.get(
    "/{user_id}/not_interested",
    summary="List Hidden For User",
)
async def list_not_interested(
    user_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[int]:
    ids = (
        await db.execute(
            text(
                """
                SELECT tmdb_id
                FROM not_interested
                WHERE user_id = :uid
                ORDER BY id DESC
                """
            ),
            {"uid": user_id},
        )
    ).scalars().all()
    return [int(x) for x in ids if x is not None]


@router.delete(
    "/{user_id}/not_interested/{tmdb_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove Hidden",
)
async def remove_not_interested(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    await db.execute(
        text(
            """
            DELETE FROM not_interested
            WHERE user_id = :uid AND tmdb_id = :tid
            """
        ),
        {"uid": user_id, "tid": tmdb_id},
    )
    await db.commit()
    return {"ok": True, "user_id": user_id, "tmdb_id": tmdb_id}
