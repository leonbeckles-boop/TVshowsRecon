# app/routes/wrapped.py

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import Rating, Show, FavoriteTmdb  # ✅ correct model names

# TMDb image base – used to build full poster URLs
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

router = APIRouter(prefix="/wrapped", tags=["wrapped"])


@router.get("/{user_id}")
async def get_wrapped(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """
    WhatNext Wrapped endpoint (v1).

    Uses:
      - Rating  (user ratings)
      - Show    (TMDb metadata, joined by tmdb_id -> show_id)
      - FavoriteTmdb (favourite shows)
    Returns a payload that matches wrapped.tsx expectations.
    """

    # ---- 1) RATINGS + SHOW JOIN ----
    q = (
        select(Rating, Show)
        .join(Show, Rating.tmdb_id == Show.show_id, isouter=True)
        .where(Rating.user_id == user_id)
    )
    rows = (await db.execute(q)).all()

    # ---- 2) FAVOURITE COUNT ----
    favorite_count = await _favorite_count(db, user_id)

    if not rows:
        # No ratings yet – return an empty but friendly payload
        return {
            "rating_count": 0,
            "favorite_count": favorite_count,
            "average_rating": None,
            "top_genres": [],
            "top_genre": None,
            "top_rated": [],
            "lowest_rated": [],
            "taste_cluster": "Start rating shows to unlock your Wrapped!",
            "activity": {},
            "recommended_next": [],
            "error": None,
        }

    # ---- 3) BASIC STATS ----
    ratings: List[float] = [r.Rating.rating for r in rows]
    avg_rating = round(sum(ratings) / len(ratings), 2)

    # ---- 4) MAP SHOWS FOR TOP / LOWEST ----
    def map_show(row: Any) -> Dict[str, Any]:
        """
        Normalise a DB row into the wrapped show shape.

        We explicitly read from row.Rating and row.Show rather than
        trying to pull scalar columns off the Row mapping.
        """
        rating: Rating = row.Rating
        show: Optional[Show] = row.Show

        # tmdb_id: prefer the rating row, fall back to show.show_id
        tmdb_id = rating.tmdb_id or (show.show_id if show else None)

        # Title: prefer show.title, then rating.title, then fallback
        title = (
            (show.title if show and getattr(show, "title", None) else None)
            or getattr(rating, "title", None)
            or "Untitled show"
        )

        # Poster path from the Show row if present
        poster_path = None
        if show is not None:
            poster_path = getattr(show, "poster_path", None)

        # Build a full poster_url; tolerate already-full URLs
        poster_url: Optional[str] = None
        if poster_path:
            poster_str = str(poster_path)
            if poster_str.startswith("http://") or poster_str.startswith("https://"):
                poster_url = poster_str
            else:
                poster_url = f"{TMDB_IMG}{poster_str}"

        # Overview from Show if present
        overview = getattr(show, "overview", None) if show is not None else None

        # Derive a year (if we have a date)
        first_air_date = getattr(show, "first_air_date", None) if show is not None else None
        year = None
        if first_air_date:
            try:
                year = int(str(first_air_date)[:4])
            except Exception:
                year = None

        return {
            "tmdb_id": tmdb_id,
            "title": title,
            "poster_path": poster_path,
            "poster_url": poster_url,
            "overview": overview,
            "year": year,
        }

    # ---- 4b) TOP / LOWEST RATED ----
    sorted_rows = sorted(rows, key=lambda r: r.Rating.rating, reverse=True)
    top_rated = [map_show(x) for x in sorted_rows[:5]]
    lowest_rated = [map_show(x) for x in sorted_rows[-3:]]

    # ---- 5) TOP GENRES (if you later add Show.genres) ----
    genre_counter: Counter[str] = Counter()
    for r in rows:
        s: Show | None = r.Show
        genres = getattr(s, "genres", None) or []
        for g in genres:
            genre_counter[g] += 1

    top_genres: List[Tuple[str, int]] = genre_counter.most_common(6)
    top_genre = top_genres[0][0] if top_genres else None

    # ---- 6) TASTE CLUSTER ----
    taste_cluster = _build_taste_cluster(top_genres, avg_rating)

    # ---- 7) SIMPLE ACTIVITY STATS ----
    activity = _compute_activity(rows)

    # ---- 8) RECOMMENDED NEXT (placeholder for now) ----
    recommended_next: List[Dict[str, Any]] = []

    return {
        "rating_count": len(rows),
        "favorite_count": favorite_count,
        "average_rating": avg_rating,
        "top_genres": top_genres,
        "top_genre": top_genre,
        "top_rated": top_rated,
        "lowest_rated": lowest_rated,
        "taste_cluster": taste_cluster,
        "activity": activity,
        "recommended_next": recommended_next,
        "error": None,
    }


async def _favorite_count(db: AsyncSession, user_id: int) -> int:
    q = (
        select(func.count())
        .select_from(FavoriteTmdb)
        .where(FavoriteTmdb.user_id == user_id)
    )
    return (await db.execute(q)).scalar_one()


def _build_taste_cluster(
    top_genres: List[Tuple[str, int]],
    avg_rating: float,
) -> str:
    if not top_genres:
        return "You have a varied taste in TV."

    main = top_genres[0][0]

    tone_map = {
        "Crime": "gritty and intense stories",
        "Drama": "big emotional character journeys",
        "Sci-Fi": "mind-bending futuristic adventures",
        "Fantasy": "epic otherworldly tales",
        "Documentary": "real-world deep dives",
        "Thriller": "high-tension psychological journeys",
    }

    tone = tone_map.get(main, "unique stories")

    if avg_rating >= 8:
        mood = "You appreciate high-quality, well-crafted TV."
    elif avg_rating >= 7:
        mood = "You enjoy a mix of solid and standout shows."
    else:
        mood = "You're pretty hard to impress."

    return f"You gravitate toward {tone}. {mood}"


def _compute_activity(rows: List[Any]) -> Dict[str, Any]:
    months: Counter[str] = Counter()
    for r in rows:
        dt: datetime | None = getattr(r.Rating, "rated_at", None)
        if dt is None:
            continue
        months[dt.strftime("%B")] += 1

    if not months:
        return {}

    most_active = months.most_common(1)[0]
    return {
        "most_active_month": most_active[0],
        "month_count": dict(months),
    }
