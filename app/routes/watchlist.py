# app/routes/watchlist.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path
from sqlalchemy import delete, select, text, bindparam
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
    """
    Returns watchlist items for user. Enriches with shows table when available.
    Output matches favourites shape where possible: tmdb_id, title, poster_url, etc.
    """

    rows = (await db.execute(
        text(
            """
            SELECT tmdb_id, added_at
            FROM user_watchlist
            WHERE user_id = :user_id
            ORDER BY added_at DESC
            """
        ),
        {"user_id": user_id},
    )).mappings().all()

    if not rows:
        return []

    tmdb_ids = [int(r["tmdb_id"]) for r in rows]

    # Enrich from shows table (your schema uses shows.show_id as the TMDb id)
    show_rows = (await db.execute(
        select(
            bindparam("dummy")  # placeholder to keep select() happy if needed
        )
    ))

    # Use a clean IN (...) expanding param to avoid ANY/ARRAY issues
    shows = (await db.execute(
        text(
            """
            SELECT show_id, title, poster_path, external_id
            FROM shows
            WHERE show_id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": tmdb_ids},
    )).mappings().all()

    show_map: Dict[int, Dict[str, Any]] = {}
    for s in shows:
        sid = int(s["show_id"])
        show_map[sid] = {
            "title": s.get("title"),
            "poster_path": s.get("poster_path"),
            "poster_url": _poster_url(s.get("poster_path")),
            "external_id": s.get("external_id"),
        }

    out: List[dict] = []
    for r in rows:
        tid = int(r["tmdb_id"])
        meta = show_map.get(tid)

        if meta:
            out.append({
                "tmdb_id": tid,
                "show_id": tid,  # keep consistent with other parts of app
                "title": meta.get("title") or f"TMDb #{tid}",
                "poster_path": meta.get("poster_path"),
                "poster_url": meta.get("poster_url"),
                "external_id": int(meta.get("external_id")) if meta.get("external_id") is not None else tid,
                "added_at": r.get("added_at"),
            })
        else:
            out.append({
                "tmdb_id": tid,
                "show_id": tid,
                "title": f"TMDb #{tid}",
                "poster_path": None,
                "poster_url": None,
                "external_id": tid,
                "added_at": r.get("added_at"),
            })

    return out


@router.post("/{user_id}/watchlist/{tmdb_id}")
async def add_watchlist_path(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    # idempotent insert
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
async def remove_watchlist_path(
    user_id: int = Path(ge=1),
    tmdb_id: int = Path(ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    await db.execute(
        text(
            """
            DELETE FROM user_watchlist
            WHERE user_id = :user_id AND tmdb_id = :tmdb_id
            """
        ),
        {"user_id": user_id, "tmdb_id": tmdb_id},
    )
    await db.commit()
    return {"ok": True}
