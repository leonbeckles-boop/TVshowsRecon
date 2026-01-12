# app/services/tmdb_service.py
from __future__ import annotations

from typing import Dict, List, Set, Any
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# existing helpers you already have
from app.services import tmdb_cached
from app.services import tmdb_details
from app.db_models import FavoriteTmdb, UserRating, NotInterested, Show


def _safe_int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def _fallback_quality(vote_average: float | None, popularity: float | None) -> float:
    """
    vote_average: 0..10 -> 0..1
    popularity:   log(1+p)/log(1+1000) -> 0..1
    """
    va = float(vote_average or 0.0)
    pop = float(popularity or 0.0)
    vote_part = max(0.0, min(va / 10.0, 1.0))
    pop_part = math.log1p(pop) / math.log1p(1000.0)
    return 0.7 * vote_part + 0.3 * pop_part


async def _user_seed_tmdb_ids(db: AsyncSession, user_id: int) -> Set[int]:
    favs = (
        await db.execute(select(FavoriteTmdb.tmdb_id).where(FavoriteTmdb.user_id == user_id))
    ).scalars().all()
    fav_set = {int(x) for x in favs if x is not None}

    rats = (
        await db.execute(select(UserRating.tmdb_id, UserRating.rating).where(UserRating.user_id == user_id))
    ).all()
    high = {int(tm) for tm, r in rats if tm is not None and r is not None and float(r) >= 7.0}

    return fav_set | high


async def _hidden_tmdb_ids(db: AsyncSession, user_id: int) -> Set[int]:
    ids = (
        await db.execute(select(NotInterested.tmdb_id).where(NotInterested.user_id == user_id))
    ).scalars().all()
    return {int(x) for x in ids if x is not None}


async def _catalogue_meta(db: AsyncSession, tmdb_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Pull title/poster/year from local Show table where available.
    """
    if not tmdb_ids:
        return {}
    rows = (
        await db.execute(select(Show).where(Show.external_id.in_([str(i) for i in tmdb_ids])))
    ).scalars().all()
    out: Dict[int, Dict[str, Any]] = {}
    for s in rows:
        tm = _safe_int(getattr(s, "external_id", None))
        if tm is None:
            continue
        out[tm] = {
            "title": getattr(s, "title", None),
            "year": getattr(s, "year", None),
            "poster_url": getattr(s, "poster_url", None),
        }
    return out


async def _ensure_quality_fields(items: List[Dict[str, Any]]) -> None:
    """
    If an item is missing both vote_average and popularity, fetch TMDb details once to fill them.
    """
    try:
        import anyio
    except Exception:
        return
    missing = [it for it in items if not (it.get("vote_average") or it.get("popularity"))]
    if not missing:
        return

    async def _fill(it: Dict[str, Any]):
        tm = _safe_int(it.get("tmdb_id") or it.get("id"))
        if tm is None:
            return
        try:
            data = await tmdb_details.get_tv_details(tm)
        except Exception:
            data = None
        if data:
            it.setdefault("vote_average", data.get("vote_average") or 0.0)
            it.setdefault("popularity", data.get("popularity") or 0.0)

    await anyio.gather(*[_fill(it) for it in missing])


async def tmdb_user_recs(
    user_id: int | None,
    limit: int = 50,
    *,
    db: AsyncSession | None = None,
) -> List[Dict]:
    """
    Return TMDb-based recs as a list of dicts:
      { tmdb_id, title, poster_url?, vote_average, popularity, score_tmdb }
    - Seeds = user's favourites ∪ ratings>=7. If no seeds, use popular fallback seeds.
    - For each seed: use cached TMDb 'similar' to collect candidates.
    - Compute score_tmdb from vote_average & popularity (+ small multi-seed boost).
    - Exclude user's hidden list and the seeds themselves.
    - Sort by score and return up to 'limit'.
    """
    if db is None:
        # No DB session -> we can't read seeds/hidden/catalogue info
        return []

    seeds: Set[int] = set()
    hidden: Set[int] = set()
    if user_id is not None:
        seeds = await _user_seed_tmdb_ids(db, user_id)
        hidden = await _hidden_tmdb_ids(db, user_id)

    if not seeds:
        # Popular, well-linked fallbacks (Breaking Bad, Game of Thrones, Stranger Things)
        seeds = {1396, 1399, 66732}

    # Collect a generous pool
    per_seed = max(10, min(60, limit * 3))
    pool: Dict[int, Dict[str, Any]] = {}

    for sid in list(seeds)[:6]:  # cap seed count to control size
        try:
            sims = await tmdb_cached.get_similar_shows_cached(int(sid), max_items=per_seed)
        except Exception:
            sims = []
        for s in sims or []:
            tm = _safe_int(s.get("id") or s.get("tmdb_id"))
            if tm is None or tm in hidden or tm in seeds:
                continue
            it = pool.setdefault(tm, {"tmdb_id": tm})
            it.setdefault("title", s.get("name") or s.get("title"))
            it.setdefault("vote_average", s.get("vote_average"))
            it.setdefault("popularity", s.get("popularity"))
            it["__hits"] = it.get("__hits", 0) + 1

    # Make sure we have quality fields where possible
    await _ensure_quality_fields(list(pool.values()))

    # Add local catalogue title/poster if available
    by_tm = await _catalogue_meta(db, list(pool.keys()))
    for tm, meta in by_tm.items():
        it = pool.get(tm)
        if not it:
            continue
        it.setdefault("title", meta.get("title"))
        if meta.get("poster_url"):
            it.setdefault("poster_url", meta["poster_url"])

    # Compute score_tmdb
    out: List[Dict[str, Any]] = []
    for tm, it in pool.items():
        qual = _fallback_quality(it.get("vote_average"), it.get("popularity"))
        hits = it.get("__hits", 1)
        # small boost for appearing under multiple seeds
        score_tmdb = qual * (1.0 + 0.1 * min(hits - 1, 3))
        out.append({
            "tmdb_id": tm,
            "title": it.get("title"),
            "poster_url": it.get("poster_url"),
            "vote_average": it.get("vote_average") or 0.0,
            "popularity": it.get("popularity") or 0.0,
            "score_tmdb": round(score_tmdb, 6),
        })

    out.sort(key=lambda x: x.get("score_tmdb", 0.0), reverse=True)
    return out[:limit]
