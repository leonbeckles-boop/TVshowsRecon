from __future__ import annotations

from typing import Any, List, Dict
import logging
import os

from fastapi import APIRouter, Depends, Query, Path, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.db_models import Show, RedditPost

import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shows", tags=["Shows"])

TMDB_API = os.environ.get("TMDB_API", "https://api.themoviedb.org/3")
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
TMDB_PROFILE_IMG = "https://image.tmdb.org/t/p/w185"

API_KEY = (
    os.environ.get("TMDB_API_KEY")
    or os.environ.get("TMDB_KEY")
    or os.environ.get("TMDB_API")
)

# Default region for watch providers (you can change to "US" if you want)
TMDB_REGION = os.environ.get("TMDB_REGION", "GB")


# ---------------------------------------------------------
# SERIALISERS
# ---------------------------------------------------------

def _serialize_show(s: Show) -> Dict[str, Any]:
    """Basic serializer for local DB show rows (used for search)."""
    return {
        "show_id": int(s.show_id),
        "tmdb_id": int(s.tmdb_id) if s.tmdb_id is not None else None,
        "title": s.title,
        "year": int(s.year) if s.year is not None else None,
        "poster_url": s.poster_url,
    }


def _serialize_post(p: RedditPost) -> Dict[str, Any]:
    created = None
    if getattr(p, "created_utc", None):
        created = p.created_utc.isoformat()

    return {
        "post_id": str(p.reddit_id or p.id),
        "title": p.title,
        "url": p.url,
        "created_at": created,
        "score": int(p.score) if p.score is not None else None,
        "subreddit": p.subreddit,
    }


# ---------------------------------------------------------
# TMDB HELPERS
# ---------------------------------------------------------

async def tmdb_fetch_details(tmdb_id: int) -> Dict[str, Any]:
    """
    Fetch full show details from TMDB.
    Used when our DB does not yet contain full metadata.
    """

    if not API_KEY:
        return {"tmdb_id": tmdb_id}

    url = f"{TMDB_API}/tv/{tmdb_id}?api_key={API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error(f"TMDB fetch failed for {tmdb_id}: {e}")
        return {"tmdb_id": tmdb_id}

    if r.status_code != 200:
        logger.warning(f"TMDB details {tmdb_id} -> HTTP {r.status_code}")
        return {"tmdb_id": tmdb_id}

    data = r.json() or {}

    poster_path = (data.get("poster_path") or "").lstrip("/")
    poster_url = f"{TMDB_IMG}/{poster_path}" if poster_path else None

    genres = data.get("genres") or []
    genre_names = [g.get("name") for g in genres if g.get("name")]
    genre_ids = [g.get("id") for g in genres if isinstance(g.get("id"), int)]

    seasons = data.get("number_of_seasons")
    episodes = data.get("number_of_episodes")
    networks = [n.get("name") for n in (data.get("networks") or [])]

    return {
        "tmdb_id": tmdb_id,
        "title": data.get("name") or data.get("original_name"),
        "overview": data.get("overview"),
        "poster_path": data.get("poster_path"),
        "poster_url": poster_url,
        "genres": genre_names,
        "genre_ids": genre_ids,
        "first_air_date": data.get("first_air_date"),
        "vote_average": data.get("vote_average"),
        "vote_count": data.get("vote_count"),
        "popularity": data.get("popularity"),
        "seasons": seasons,
        "episodes": episodes,
        "networks": networks,
    }


async def tmdb_fetch_watch_providers(tmdb_id: int) -> Dict[str, List[str]]:
    """
    Fetch watch providers (where to watch) from TMDB.

    Returns:
      {
        "flatrate": ["Netflix", "Disney+"],
        "buy": ["Apple TV"],
        "rent": ["Amazon Video"]
      }
    """
    if not API_KEY:
        return {}

    url = f"{TMDB_API}/tv/{tmdb_id}/watch/providers?api_key={API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error(f"TMDB watch providers failed for {tmdb_id}: {e}")
        return {}

    if r.status_code != 200:
        logger.warning(f"TMDB watch providers {tmdb_id} -> HTTP {r.status_code}")
        return {}

    data = r.json() or {}
    results = data.get("results") or {}

    # Prefer configured region (e.g. GB), then fall back to US if present
    region_data = results.get(TMDB_REGION) or results.get("US") or {}
    flatrate = region_data.get("flatrate") or []
    buy = region_data.get("buy") or []
    rent = region_data.get("rent") or []

    def names(items):
        return [p.get("provider_name") for p in items if p.get("provider_name")]

    return {
        "flatrate": names(flatrate),
        "buy": names(buy),
        "rent": names(rent),
    }


async def tmdb_fetch_similar(tmdb_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Fetch similar TV shows from TMDB.
    Returns lightweight TMDB items suitable for ShowCard.
    """
    if not API_KEY:
        return []

    url = f"{TMDB_API}/tv/{tmdb_id}/similar?api_key={API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error(f"TMDB similar failed for {tmdb_id}: {e}")
        return []

    if r.status_code != 200:
        logger.warning(f"TMDB similar {tmdb_id} -> HTTP {r.status_code}")
        return []

    data = r.json() or {}
    results = data.get("results") or []

    out: List[Dict[str, Any]] = []
    for row in results[:limit]:
        tid = row.get("id")
        if not isinstance(tid, int):
            continue

        out.append(
            {
                "tmdb_id": tid,
                "title": row.get("name") or row.get("original_name"),
                "overview": row.get("overview"),
                "poster_path": row.get("poster_path"),
                "vote_average": row.get("vote_average"),
                "vote_count": row.get("vote_count"),
                "first_air_date": row.get("first_air_date"),
                "genre_ids": row.get("genre_ids") or [],
                "original_language": row.get("original_language"),
            }
        )

    return out


async def tmdb_fetch_videos(tmdb_id: int) -> List[Dict[str, Any]]:
    """
    Fetch TMDB videos (trailers, teasers, etc.) for a show.
    Returns a cleaned list of video objects.
    """
    if not API_KEY:
        return []

    url = f"{TMDB_API}/tv/{tmdb_id}/videos?api_key={API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error(f"TMDB videos failed for {tmdb_id}: {e}")
        return []

    if r.status_code != 200:
        logger.warning(f"TMDB videos {tmdb_id} -> HTTP {r.status_code}")
        return []

    data = r.json() or {}
    results = data.get("results") or []

    videos: List[Dict[str, Any]] = []
    for v in results:
        key = v.get("key")
        site = v.get("site")
        if not key or not site:
            continue

        videos.append(
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "key": key,
                "site": site,
                "type": v.get("type"),
                "official": bool(v.get("official")),
                "published_at": v.get("published_at"),
            }
        )

    return videos


async def tmdb_fetch_credits(tmdb_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch cast and crew from TMDB.
    Returns a dict with 'cast' and 'crew' lists.
    """
    if not API_KEY:
        return {"cast": [], "crew": []}

    url = f"{TMDB_API}/tv/{tmdb_id}/credits?api_key={API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error(f"TMDB credits failed for {tmdb_id}: {e}")
        return {"cast": [], "crew": []}

    if r.status_code != 200:
        logger.warning(f"TMDB credits {tmdb_id} -> HTTP {r.status_code}")
        return {"cast": [], "crew": []}

    data = r.json() or {}
    cast_raw = data.get("cast") or []
    crew_raw = data.get("crew") or []

    cast: List[Dict[str, Any]] = []
    for c in cast_raw:
        name = c.get("name")
        if not name:
            continue
        profile_path = c.get("profile_path") or None
        profile_url = None
        if profile_path:
            profile_url = f"{TMDB_PROFILE_IMG}/{profile_path.lstrip('/')}"
        cast.append(
            {
                "id": c.get("id"),
                "name": name,
                "character": c.get("character"),
                "order": c.get("order"),
                "profile_path": profile_path,
                "profile_url": profile_url,
            }
        )

    crew: List[Dict[str, Any]] = []
    for m in crew_raw:
        name = m.get("name")
        if not name:
            continue
        crew.append(
            {
                "id": m.get("id"),
                "name": name,
                "job": m.get("job"),
                "department": m.get("department"),
            }
        )

    return {"cast": cast, "crew": crew}


# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------

@router.get("", summary="Search shows (local DB only)")
async def search_shows(
    q: str = Query(..., min_length=1),
    limit: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    """
    Simple substring search from local DB (orders by title).
    """
    try:
        stmt = (
            select(Show)
            .where(Show.title.ilike(f"%{q}%"))
            .order_by(Show.title.asc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_serialize_show(s) for s in rows]
    except Exception as e:
        logger.exception("Search shows failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {e!r}")


@router.get("/{tmdb_id}/posts", summary="Recent Reddit posts for a show")
async def show_posts(
    tmdb_id: int = Path(..., ge=1),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    """
    Fetch Reddit posts using show_id (NOT tmdb_id).
    reddit_posts table does NOT contain tmdb_id for older records.
    """

    # 1. Resolve tmdb_id → show_id
    stmt = select(Show).where(Show.tmdb_id == tmdb_id)
    show_row = (await db.execute(stmt)).scalar_one_or_none()

    if not show_row:
        return []   # No posts if we don't even know the local show_id

    # 2. Fetch Reddit posts by show_id
    stmt_posts = (
        select(RedditPost)
        .where(RedditPost.show_id == show_row.show_id)
        .order_by(RedditPost.created_utc.desc())
        .limit(limit)
    )

    posts = (await db.execute(stmt_posts)).scalars().all()

    # 3. Serialize output
    return [_serialize_post(p) for p in posts]


@router.get("/details/{tmdb_id}", summary="Full details for a show")
async def show_details(
    tmdb_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """
    Unified Show Details endpoint.

    Flow:
    1. Try to load from local DB (poster_url, year, etc.)
    2. Fetch full TMDB details
    3. Fetch watch providers (where to watch)
    4. Fetch videos (trailers) and credits (cast)
    5. Merge everything into one JSON
    """

    # --- Step 1: Try local database ---
    try:
        stmt = select(Show).where(Show.tmdb_id == tmdb_id)
        row = (await db.execute(stmt)).scalar_one_or_none()
    except Exception:
        row = None

    local: Dict[str, Any] = {}
    if row:
        local = {
            "tmdb_id": row.tmdb_id,
            "title": row.title,
            "year": row.year,
            "poster_url": row.poster_url,
        }

    # --- Step 2: TMDB details ---
    tmdb = await tmdb_fetch_details(tmdb_id)

    # --- Step 3: watch providers ---
    watch_providers = await tmdb_fetch_watch_providers(tmdb_id)

    # --- Step 4: videos + credits ---
    videos = await tmdb_fetch_videos(tmdb_id)
    credits = await tmdb_fetch_credits(tmdb_id)
    cast = credits.get("cast", [])

    # Pick a primary trailer: prefer official YouTube trailers, then any YouTube video
    primary_trailer: Dict[str, Any] | None = None
    if videos:
        # official YouTube trailers
        candidates = [
            v
            for v in videos
            if v.get("site") == "YouTube"
            and (v.get("type") == "Trailer")
            and v.get("official")
        ]
        if not candidates:
            # any YouTube trailer/teaser
            candidates = [
                v
                for v in videos
                if v.get("site") == "YouTube"
                and v.get("type") in {"Trailer", "Teaser"}
            ]
        if not candidates:
            candidates = [v for v in videos if v.get("site") == "YouTube"]

        if candidates:
            primary_trailer = candidates[0]

    # --- Step 5: Merge ---
    out: Dict[str, Any] = {}
    out.update(tmdb)

    # Local overrides / fills gaps if TMDB missing
    for k, v in local.items():
        if v is not None and not out.get(k):
            out[k] = v

    # Attach providers and query_title helper
    out["watch_providers"] = watch_providers
    out["query_title"] = out.get("title")

    # Attach videos / trailer / cast
    out["videos"] = videos
    out["primary_trailer"] = primary_trailer
    # keep cast small(ish) by default; front-end can still slice
    out["cast"] = cast[:12] if cast else []

    return out


# Alias so frontend /api/shows/{tmdb_id} works
@router.get("/{tmdb_id}", summary="Full details for a show (alias for /details/{tmdb_id})")
async def show_details_alias(
    tmdb_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """
    Compatibility alias for the ShowDetails page.

    Frontend calls /api/shows/{tmdb_id}, so this delegates to the
    existing /details/{tmdb_id} implementation.
    """
    return await show_details(tmdb_id=tmdb_id, db=db)


@router.get("/{tmdb_id}/similar", summary="Similar shows from TMDB")
async def similar_shows(
    tmdb_id: int = Path(..., ge=1),
) -> List[Dict[str, Any]]:
    """
    Public API route for similar shows (via TMDB).
    """
    try:
        return await tmdb_fetch_similar(tmdb_id, limit=20)
    except Exception as e:
        logger.exception("Similar shows failed")
        raise HTTPException(status_code=500, detail=f"Similar shows failed: {e}")


@router.get("/{tmdb_id}/reddit-similar", summary="Reddit-based similar shows")
async def reddit_similar(
    tmdb_id: int = Path(..., ge=1),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    """
    Returns shows that are strongly co-mentioned with this show on Reddit.
    Uses reddit_pairs table, then hydrates each TMDB id with TMDB details
    so the front-end has title/poster/overview etc for ShowCard.
    """

    sql = text("""
        SELECT
            CASE
                WHEN tmdb_id_a = :tid THEN tmdb_id_b
                ELSE tmdb_id_a
            END AS other_id,
            pair_weight
        FROM reddit_pairs
        WHERE tmdb_id_a = :tid OR tmdb_id_b = :tid
        ORDER BY pair_weight DESC
        LIMIT :limit
    """)

    rows = (await db.execute(sql, {"tid": tmdb_id, "limit": limit})).mappings().all()
    if not rows:
        return []

    out: List[Dict[str, Any]] = []

    for r in rows:
        other_id = int(r["other_id"])
        pair_weight = float(r["pair_weight"])

        # Fetch TMDB details for each related show
        details = await tmdb_fetch_details(other_id)

        out.append(
            {
                "tmdb_id": other_id,
                "title": details.get("title"),
                "overview": details.get("overview"),
                "poster_path": details.get("poster_path"),
                "poster_url": details.get("poster_url"),
                "vote_average": details.get("vote_average"),
                "vote_count": details.get("vote_count"),
                "first_air_date": details.get("first_air_date"),
                "genres": details.get("genres"),
                "genre_ids": details.get("genre_ids"),
                "pair_weight": pair_weight,
            }
        )

    return out
