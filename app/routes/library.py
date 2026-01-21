
from typing import Any, List
from fastapi import APIRouter, Depends, Path
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth.dependencies import require_user
from app.db.async_session import get_async_db
from app.db_models import Show, FavoriteTmdb

router = APIRouter()

@router.get("/favorites")
async def list_favorites_for_current_user(
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[dict]:
    user_id = int(user["id"])

    res = await db.execute(
        text("SELECT tmdb_id FROM user_favorites WHERE user_id = :uid ORDER BY id DESC"),
        {"uid": user_id},
    )
    fav_ids = [int(x) for (x,) in res.fetchall() if x is not None]
    if not fav_ids:
        return []

    shows = (await db.execute(select(Show).where(Show.show_id.in_(fav_ids)))).scalars().all()
    by_id = {int(s.show_id): s for s in shows}

    out: List[dict] = []
    for tmdb_id in fav_ids:
        s = by_id.get(int(tmdb_id))
        if s:
            poster_path = getattr(s, "poster_path", None)
            poster_url = getattr(s, "poster_url", None)
            if not poster_url and poster_path:
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
            out.append({
                "tmdb_id": int(tmdb_id),
                "show_id": int(s.show_id),
                "title": s.title,
                "year": int(s.year) if getattr(s, "year", None) is not None else None,
                "poster_path": poster_path,
                "poster_url": poster_url,
            })
        else:
            out.append({
                "tmdb_id": int(tmdb_id),
                "show_id": int(tmdb_id),
                "title": f"TMDb #{int(tmdb_id)}",
                "year": None,
                "poster_path": None,
                "poster_url": None,
            })
    return out
