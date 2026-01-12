# app/services/hybrid_service.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple
import math

# TMDb (cached similar)
from app.services import tmdb_cached

# Reddit — optional; we guard imports so missing service doesn't crash
try:
    from app.services.reddit_service import reddit_mention_counts_generic  # hypothetical generic fn
except Exception:
    reddit_mention_counts_generic = None  # type: ignore


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _fallback_quality(vote_average: Any, popularity: Any) -> float:
    """
    Derive a stable quality score in [0, 1] from TMDb:
      - vote_average: 0..10 -> 0..1
      - popularity:   log(1+p)/log(1+1000) -> 0..1
    Final = 0.7*vote + 0.3*pop
    """
    va = _safe_float(vote_average, 0.0)
    pop = _safe_float(popularity, 0.0)
    vote_part = max(0.0, min(va / 10.0, 1.0))
    pop_part = math.log1p(pop) / math.log1p(1000.0) if pop > 0 else 0.0
    return 0.7 * vote_part + 0.3 * pop_part


def _normalize(values: List[float]) -> List[float]:
    """
    Min-max normalize to [0,1]. If empty or all equal, return zeros.
    """
    if not values:
        return []
    vmin, vmax = min(values), max(values)
    if vmax <= vmin:
        return [0.0 for _ in values]
    rng = vmax - vmin
    return [(v - vmin) / rng for v in values]


async def _gather_tmdb_similar(seeds: Iterable[int], max_items: int) -> Dict[int, Dict[str, Any]]:
    """
    For each seed, pull cached similar shows and build a candidate pool keyed by tmdb_id.
    Adds a "__hits" counter to reflect how many seeds nominated the same item.
    """
    pool: Dict[int, Dict[str, Any]] = {}
    if not seeds:
        return pool

    per_seed = max(10, min(100, max_items * 3))
    for sid in list(seeds)[:8]:  # cap seed count to control size
        try:
            similar = await tmdb_cached.get_similar_shows_cached(int(sid), max_items=per_seed)
        except Exception:
            similar = []
        for rec in similar or []:
            tmdb_id = rec.get("id") or rec.get("tmdb_id")
            if not tmdb_id:
                continue
            tm = int(tmdb_id)
            it = pool.setdefault(tm, {"id": tm})
            # carry useful fields if available
            if rec.get("name") and not it.get("title"):
                it["title"] = rec["name"]
            if rec.get("title") and not it.get("title"):
                it["title"] = rec["title"]
            if rec.get("poster_url"):
                it.setdefault("poster_url", rec["poster_url"])
            if rec.get("poster_path") and not it.get("poster_url"):
                it["poster_url"] = rec["poster_path"]  # tmdb_cached may already transform this

            # numeric quality hints
            if "vote_average" in rec:
                it.setdefault("vote_average", rec.get("vote_average"))
            if "popularity" in rec:
                it.setdefault("popularity", rec.get("popularity"))

            it["__hits"] = it.get("__hits", 0) + 1

    return pool


async def hybrid_recs(
    seeds_tmdb: Iterable[int],
    *,
    limit: int = 50,
    w_tmdb: float = 0.7,
    w_reddit: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    Blend TMDb-similar & (optional) generic Reddit mention scores into a base candidate list.
    This function is intentionally DB-free; the adapter handles user-specific DB filtering.

    Returns a list of dicts with at least:
      { "id": <tmdb_id>, "title"?, "poster_url"?, "vote_average"?, "popularity"?, "score": <float> }
    """
    seeds = [int(s) for s in seeds_tmdb if s is not None]
    # ---- TMDb pool ----
    pool = await _gather_tmdb_similar(seeds, max_items=max(50, limit * 4))

    # If TMDb pool is empty (no API key, rate limit, or no seeds), return empty to let adapter fetch details later.
    if not pool:
        return []

    # Compute TMDb quality scores and multi-seed boost
    tmdb_ids: List[int] = []
    tmdb_scores_raw: List[float] = []
    for tm, it in pool.items():
        qual = _fallback_quality(it.get("vote_average"), it.get("popularity"))
        hits = int(it.get("__hits", 1))
        # 10% boost per extra seed match, up to +30%
        boosted = qual * (1.0 + 0.1 * min(hits - 1, 3))
        tmdb_ids.append(tm)
        tmdb_scores_raw.append(boosted)

    # Normalize TMDb scores to [0,1] for a stable blend
    tmdb_scores = _normalize(tmdb_scores_raw)

    # Map normalized tmdb score by id
    tscore_by_id: Dict[int, float] = {tm: sc for tm, sc in zip(tmdb_ids, tmdb_scores)} if tmdb_ids else {}

    # ---- Reddit generic (optional) ----
    # If you wire a generic, non-user reddit scorer, plug it here.
    # For now, we treat reddit as empty unless a function is available.
    rscore_by_id: Dict[int, float] = {}
    if callable(reddit_mention_counts_generic):
        try:
            # Expecting a dict { tmdb_id: mention_score } already in 0..1 or any scale; we'll min-max it.
            rraw_map = await reddit_mention_counts_generic(limit_total=200)
            if rraw_map:
                ids = list(rraw_map.keys())
                vals = [_safe_float(rraw_map[i], 0.0) for i in ids]
                nvals = _normalize(vals)
                rscore_by_id = {i: v for i, v in zip(ids, nvals)}
        except Exception:
            rscore_by_id = {}

    # ---- Blend & build output ----
    out: List[Dict[str, Any]] = []
    for tm in tmdb_ids:
        it = pool[tm]
        base_tmdb = tscore_by_id.get(tm, 0.0)
        base_reddit = rscore_by_id.get(tm, 0.0)
        score = (w_tmdb * base_tmdb) + (w_reddit * base_reddit)
        # ensure tiny epsilon to avoid all-zero downstream if both sources 0
        score = max(score, 0.0001)
        out.append({
            "id": tm,
            "title": it.get("title"),
            "poster_url": it.get("poster_url"),
            "vote_average": _safe_float(it.get("vote_average"), 0.0),
            "popularity": _safe_float(it.get("popularity"), 0.0),
            "score": round(score, 6),
        })

    # Sort by blended score desc & trim
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]
