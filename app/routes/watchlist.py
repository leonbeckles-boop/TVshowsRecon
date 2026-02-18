from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path
from sqlalchemy import text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.security import require_user

router = APIRouter(prefix="/users", tags=["watchlist"])

TMDB_IMG = "https://image.tmdb.org/t/p/w500"


def _poster_url(poster_path: Optional[str]) -> Optional[str]:
    if not poster_path:
        return None
    if poster_path.startswith("http"):
        return poster_path
    return f"{TMDB_IMG}{poster_path}"


@router.get("/{user_id}/watchlist")
async def list_watchlist_for_user(
    user_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict]:

    rows = (
        await db.execute(
            text(
                """
                SELECT tmdb_id, added_at
                FROM user_watchlist
                WHERE user_id = :user_id
                ORDER BY added_at DESC
                """
            ),
            {"user_id": user_id},
        )
    ).mappings().all()

    if not rows:
        return []

    tmdb_ids = [int(r["tmdb_id"]) for r in rows]

    shows = (
        await db.execute(
            text(
                """
                SELECT show_id, title, poster_path
                FROM shows
                WHERE show_id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": tmdb_ids},
        )
    ).mappings().all()

    show_map: Dict[int, Dict[str, Any]] = {}
    for s in shows:
        show_map[int(s["show_id"])] = {
            "title": s["title"],
            "poster_path": s["poster_path"],
        }

    result = []

    for r in rows:
        tmdb_id = int(r["tmdb_id"])
        meta = show_map.get(tmdb_id, {})

        result.append(
            {
                "tmdb_id": tmdb_id,
                "show_id": tmdb_id,
                "title": meta.get("title") or f"TMDb #{tmdb_id}",
                "poster_path": meta.get("poster_path"),
                "poster_url": _poster_url(meta.get("poster_path")),
                "added_at": r["added_at"],
            }
        )

    return result


@router.post("/{user_id}/watchlist/{tmdb_id}")
async def add_watchlist(
    user_id: int,
    tmdb_id: int,
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
):

    await db.execute(
        text(
            """
            INSERT INTO user_watchlist (user_id, tmdb_id)
            VALUES (:user_id, :tmdb_id)
            ON CONFLICT (user_id, tmdb_id) DO NOTHING
            """
        ),
        {"user_id": user_id, "tmdb_id": tmdb_id},
    )

    await db.commit()

    return {"ok": True}


@router.delete("/{user_id}/watchlist/{tmdb_id}")
async def remove_watchlist(
    user_id: int,
    tmdb_id: int,
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
):

    await db.execute(
        text(
            """
            DELETE FROM user_watchlist
            WHERE user_id = :user_id
              AND tmdb_id = :tmdb_id
            """
        ),
        {"user_id": user_id, "tmdb_id": tmdb_id},
    )

    await db.commit()

    return {"ok": True}
