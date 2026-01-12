from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, AsyncIterator

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager

# ---------------------------------------------------------------------------
# DB session wiring
# ---------------------------------------------------------------------------

try:
    # NOTE: this is the correct path in your project now
    from app.db.session import AsyncSessionLocal, get_async_session
except ImportError:  # very defensive fallback
    AsyncSessionLocal = None  # type: ignore

    async def get_async_session() -> AsyncIterator[AsyncSession]:  # type: ignore
        raise RuntimeError("get_async_session not available")


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """
    Unified way to get an AsyncSession that works whether we have
    AsyncSessionLocal (normal case) or only get_async_session() generator.
    """
    if AsyncSessionLocal is not None:
        async with AsyncSessionLocal() as session:  # type: ignore[arg-type]
            yield session
    else:
        gen = get_async_session()
        session = await gen.__anext__()  # type: ignore[call-arg]
        try:
            yield session
        finally:
            await gen.aclose()  # type: ignore[func-returns-value]

# ---------------------------------------------------------------------------
# TMDB helpers (copied from v1-style logic)
# ---------------------------------------------------------------------------

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"


def _get_tmdb_api_key() -> str | None:
    return (
        os.environ.get("TMDB_API_KEY")
        or os.environ.get("TMDB_KEY")
        or os.environ.get("TMDB_API")
    )


async def _tmdb_details(tmdb_id: int) -> Dict[str, Any]:
    """
    Fetch details for a single TMDb TV show.
    Returns a dict including poster_url, genres, etc.
    Falls back gracefully if TMDb key is missing or request fails.
    """
    api_key = _get_tmdb_api_key()
    base: Dict[str, Any] = {"tmdb_id": tmdb_id}

    if not api_key:
        # No TMDb key configured – return barebones info
        return base

    url = f"{TMDB_API}/tv/{tmdb_id}?api_key={api_key}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
    except Exception:
        # Network/timeout issues: just return barebones
        return base

    if r.status_code != 200:
        return base

    data = r.json()

    poster_path = (data.get("poster_path") or "").lstrip("/")
    poster_url = f"{TMDB_IMG}/{poster_path}" if poster_path else None

    # Genres
    genres_arr = data.get("genres") or []
    genre_names = [
        str(g.get("name")).strip()
        for g in genres_arr
        if g and g.get("name")
    ]
    genre_ids = [
        int(g.get("id"))
        for g in genres_arr
        if g and isinstance(g.get("id"), int)
    ]

    # Enriched payload (very similar to v1)
    enriched: Dict[str, Any] = {
        "tmdb_id": tmdb_id,
        "name": data.get("name") or data.get("original_name"),
        "title": data.get("name") or data.get("original_name"),
        "overview": data.get("overview"),
        "poster_path": data.get("poster_path"),
        "poster_url": poster_url,
        "first_air_date": data.get("first_air_date"),
        "origin_country": data.get("origin_country"),
        "original_language": data.get("original_language"),
        "genres": genre_names,
        "genre_ids": genre_ids,
        # Extra fields that your UI might like
        "vote_average": data.get("vote_average"),
        "vote_count": data.get("vote_count"),
        "popularity": data.get("popularity"),
    }

    return enriched


async def _tmdb_bulk_details(tmdb_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Fetch TMDb details for many ids in parallel.
    Returns { tmdb_id: details_dict }.
    """
    unique_ids = sorted({int(t) for t in tmdb_ids if t is not None})

    if not unique_ids:
        return {}

    # basic parallelism
    tasks = [asyncio.create_task(_tmdb_details(tid)) for tid in unique_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: Dict[int, Dict[str, Any]] = {}
    for tid, result in zip(unique_ids, results):
        if isinstance(result, Exception):
            out[tid] = {"tmdb_id": tid}
        else:
            out[tid] = result  # type: ignore[assignment]
    return out


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------

# Personalised weights (precomputed into user_reddit_pairs)
SQL_USER_PAIRS = text(
    """
    SELECT suggested_tmdb_id, weight
    FROM user_reddit_pairs
    WHERE user_id = :uid
    ORDER BY weight DESC
    LIMIT :limit
    """
)

# Fallback: build from raw reddit_pairs + favorites if user_reddit_pairs empty
SQL_FALLBACK_AGG = text(
    """
    WITH seeds AS (
        SELECT tmdb_id
        FROM user_favorites
        WHERE user_id = :uid
    ),
    both_dirs AS (
        SELECT rp.tmdb_id_b AS suggested, rp.pair_weight AS w
        FROM reddit_pairs rp
        JOIN seeds s ON s.tmdb_id = rp.tmdb_id_a
        UNION ALL
        SELECT rp.tmdb_id_a AS suggested, rp.pair_weight AS w
        FROM reddit_pairs rp
        JOIN seeds s ON s.tmdb_id = rp.tmdb_id_b
    ),
    agg AS (
        SELECT suggested, SUM(w) AS w
        FROM both_dirs
        GROUP BY suggested
    )
    SELECT suggested AS suggested_tmdb_id, w
    FROM agg
    ORDER BY w DESC
    LIMIT :limit
    """
)

SQL_FAVORITES = text(
    "SELECT tmdb_id FROM user_favorites WHERE user_id = :uid"
)

SQL_NOT_INTERESTED = text(
    "SELECT tmdb_id FROM not_interested WHERE user_id = :uid"
)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/recs/v2", tags=["recs-v2"])


@router.get("/diag-ez")
async def diag_ez() -> Dict[str, Any]:
    """Very cheap health-check endpoint."""
    return {"ok": True, "who": "recs_v2"}


@router.get("/_diag_v1/{user_id}")
async def _diag_v1(user_id: int, limit: int = 20) -> Dict[str, Any]:
    """
    Debug-only: show the raw IDs & weights before TMDb enrichment & filtering.
    Helpful when diagnosing behaviour.
    """
    async with session_scope() as session:
        rows = (await session.execute(SQL_USER_PAIRS, {"uid": user_id, "limit": limit})).all()
        items = [
            {"tmdb_id": int(r[0]), "weight": float(r[1])}
            for r in rows
        ]
    return {"user_id": user_id, "items": items}


@router.get("/{user_id}")
async def get_recs_v2(
    user_id: int,
    limit: int = Query(36, ge=1, le=200),
    mmr_lambda: float = Query(0.3, ge=0.0, le=1.0),
    flat: int = Query(1, ge=0, le=1),
) -> Any:
    """
    v2 – Reddit-based personalised recommendations.

    Steps:
      1) Read favourites + not_interested for this user.
      2) Pull top suggestions from user_reddit_pairs (precomputed).
         - If empty, fall back to aggregating reddit_pairs live.
      3) Filter out favourites + not_interested.
      4) Normalise weights into [0,1] as `score`.
      5) Fetch TMDb details (title, overview, poster, genres, etc.)
      6) Return enriched items, ready for smarter scoring / MMR later.
    """
    async with session_scope() as session:
        # ------------------------------------------------------------------
        # 1) load favourites + hidden
        # ------------------------------------------------------------------
        fav_rows = (await session.execute(SQL_FAVORITES, {"uid": user_id})).all()
        hide_rows = (await session.execute(SQL_NOT_INTERESTED, {"uid": user_id})).all()

        favorite_ids = {int(r[0]) for r in fav_rows}
        hidden_ids = {int(r[0]) for r in hide_rows}

        # ------------------------------------------------------------------
        # 2) primary source: user_reddit_pairs
        #    we oversample a bit so we can drop fav/hidden and still have `limit`
        # ------------------------------------------------------------------
        oversample = limit * 3
        rows = (await session.execute(
            SQL_USER_PAIRS,
            {"uid": user_id, "limit": oversample},
        )).all()

        if not rows:
            # ------------------------------------------------------------------
            # 3) fallback: build from raw reddit_pairs + favourites
            # ------------------------------------------------------------------
            rows = (await session.execute(
                SQL_FALLBACK_AGG,
                {"uid": user_id, "limit": oversample},
            )).all()

        # rows: [(suggested_tmdb_id, weight), ...]
        candidates: List[Dict[str, Any]] = []
        for suggested_tmdb_id, w in rows:
            tid = int(suggested_tmdb_id)
            if tid in favorite_ids or tid in hidden_ids:
                continue
            candidates.append({"tmdb_id": tid, "score_raw": float(w)})
            if len(candidates) >= limit:
                break

        if not candidates:
            # Nothing to recommend
            return [] if flat else {"items": [], "meta": {"engine": "v2", "user_id": user_id}}

        # ------------------------------------------------------------------
        # 4) normalise weights into [0,1] as score (MMR-ready)
        # ------------------------------------------------------------------
        max_w = max(c["score_raw"] for c in candidates) or 1.0
        for c in candidates:
            c["score"] = c["score_raw"] / max_w

        # NOTE: `mmr_lambda` is accepted here so we can later plug real
        # MMR re-ranking in without changing the API. For now, we simply
        # keep the Reddit ordering and expose the normalised `score`.

        # ------------------------------------------------------------------
        # 5) fetch TMDb details
        # ------------------------------------------------------------------
        tmdb_ids = [c["tmdb_id"] for c in candidates]
        details_map = await _tmdb_bulk_details(tmdb_ids)

        items: List[Dict[str, Any]] = []
        for c in candidates:
            tid = c["tmdb_id"]
            meta = details_map.get(tid, {"tmdb_id": tid})
            combined = {
                **meta,
                "score": c["score"],
                "score_raw": c["score_raw"],
                "source": "reddit_v2",
            }
            # Ensure we always have a `title` field for the UI
            if not combined.get("title") and combined.get("name"):
                combined["title"] = combined["name"]
            items.append(combined)

    if flat == 1:
        return items

    meta = {
        "engine": "v2",
        "user_id": user_id,
        "limit": limit,
        "mmr_lambda": mmr_lambda,
        "count": len(items),
    }
    return {"items": items, "meta": meta}
