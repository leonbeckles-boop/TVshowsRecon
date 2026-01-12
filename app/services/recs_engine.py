# app/services/recs_engine.py
from __future__ import annotations

from typing import Any, Dict, List, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import Show, FavoriteTmdb, Rating, NotInterested


def _safe_int(v: str | int | None) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def _load_user_profile(db: AsyncSession, user_id: int) -> dict[str, Any]:
    # Favorites (TMDb ids)
    fav_ids = (
        await db.execute(
            select(FavoriteTmdb.tmdb_id).where(FavoriteTmdb.user_id == user_id)
        )
    ).scalars().all()
    favorites: Set[int] = {int(x) for x in fav_ids if x is not None}

    # Ratings (TMDb id -> rating)
    rows = (
        await db.execute(
            select(Rating.tmdb_id, Rating.rating).where(Rating.user_id == user_id)
        )
    ).all()
    ratings: Dict[int, float] = {
        int(tmdb): float(score)
        for tmdb, score in rows
        if tmdb is not None and score is not None
    }

    # Not interested
    ni_ids = (
        await db.execute(
            select(NotInterested.tmdb_id).where(NotInterested.user_id == user_id)
        )
    ).scalars().all()
    not_interested: Set[int] = {int(x) for x in ni_ids if x is not None}

    return {
        "favorites": favorites,
        "ratings": ratings,
        "not_interested": not_interested,
    }


async def _load_catalog(db: AsyncSession) -> list[Show]:
    return (await db.execute(select(Show))).scalars().all()


def _score(tmdb_id: int | None, profile: dict[str, Any]) -> float:
    if tmdb_id is None:
        return 0.0
    score = 0.0
    if tmdb_id in profile["favorites"]:
        score += 2.5
    if tmdb_id in profile["ratings"]:
        # normalize 0..10 to up to +2.0
        score += profile["ratings"][tmdb_id] / 5.0
    return score


async def recommend_for_user(
    db: AsyncSession, user_id: int, limit: int = 20
) -> list[dict[str, Any]]:
    """
    Simple, robust recommender:

    - loads favorites, ratings, not_interested
    - loads local catalogue (Show)
    - scores shows by favorites/ratings
    - filters out not_interested and already interacted (favorited/rated)
    - returns top N (ties by newest year then title)
    """
    profile = await _load_user_profile(db, user_id)
    shows = await _load_catalog(db)

    results: list[dict[str, Any]] = []
    for s in shows:
        tmdb = _safe_int(s.external_id)
        if tmdb is None:
            continue

        if (
            tmdb in profile["not_interested"]
            or tmdb in profile["favorites"]
            or tmdb in profile["ratings"]
        ):
            # don't recommend what the user hid or already interacted with
            continue

        results.append(
            {
                "show_id": s.show_id,
                "tmdb_id": tmdb,
                "title": s.title,
                "year": s.year,
                "poster_url": s.poster_url,
                "score": round(_score(tmdb, profile), 4),
            }
        )

    results.sort(
        key=lambda r: (r["score"], r.get("year") or 0, r.get("title") or ""),
        reverse=True,
    )
    return results[: max(1, int(limit))]
