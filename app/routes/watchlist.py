from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Path, Request
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
    request: Request,
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

    # 1) Pull what we can from local shows table
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
            "title": s.get("title"),
            "poster_path": s.get("poster_path"),
        }

    missing = [tid for tid in tmdb_ids if tid not in show_map]

    # 2) Fallback to TMDb for missing ids
    tmdb_client = request.app.state.tmdb_client
    api_key = request.app.state.get("tmdb_api_key") if hasattr(request.app, "state") else None

    # In your app you likely keep TMDB key in env, so just read env directly if needed:
    # But we’ll avoid importing os here and instead rely on your tmdb client being set up with key handling elsewhere.
    #
    # If your TMDb routes already work, the key is available; we can call the real TMDb endpoint directly.
    async def fetch_tmdb_tv(tid: int) -> Optional[Tuple[str, Optional[str]]]:
        try:
            # Use the same TMDB key mechanism as your tmdb routes:
            # Most implementations use env var TMDB_API_KEY and pass it as ?api_key=
            # If your tmdb_client does not auto-attach, this still works if the key is in env and you already do it elsewhere.
            import os

            key = os.getenv("TMDB_API_KEY")
            if not key:
                return None

            url = f"https://api.themoviedb.org/3/tv/{tid}"
            res = await tmdb_client.get(url, params={"api_key": key})
            if res.status_code != 200:
                return None
            j = res.json()
            title = j.get("name") or j.get("original_name") or f"TMDb #{tid}"
            poster_path = j.get("poster_path")
            return title, poster_path
        except Exception:
            return None

    fetched: Dict[int, Dict[str, Any]] = {}

    for tid in missing:
        data = await fetch_tmdb_tv(tid)
        if not data:
            continue
        title, poster_path = data
        fetched[tid] = {"title": title, "poster_path": poster_path}

    # 3) (Optional but recommended) upsert fetched into shows table so future loads are fast
    # Your shows table uses show_id as the TMDb id, title, poster_path.
    for tid, meta in fetched.items():
        try:
            await db.execute(
                text(
                    """
                    INSERT INTO shows (show_id, title, poster_path)
                    VALUES (:show_id, :title, :poster_path)
                    ON CONFLICT (show_id) DO UPDATE
                      SET title = EXCLUDED.title,
                          poster_path = EXCLUDED.poster_path
                    """
                ),
                {"show_id": tid, "title": meta["title"], "poster_path": meta["poster_path"]},
            )
        except Exception:
            # If your shows table has required columns beyond these, the insert may fail.
            # In that case, we still return the TMDb-fetched data without caching.
            pass

    if fetched:
        await db.commit()

    # Merge fetched into show_map for response
    for tid, meta in fetched.items():
        show_map[tid] = meta

    # 4) Build response in the same order as watchlist rows
    result: List[dict] = []
    for r in rows:
        tid = int(r["tmdb_id"])
        meta = show_map.get(tid, {})
        poster_path = meta.get("poster_path")
        result.append(
            {
                "tmdb_id": tid,
                "show_id": tid,
                "title": meta.get("title") or f"TMDb #{tid}",
                "poster_path": poster_path,
                "poster_url": _poster_url(poster_path),
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
