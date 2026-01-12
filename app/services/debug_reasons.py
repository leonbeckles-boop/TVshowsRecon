from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional
from datetime import datetime

def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def enrich_debug_reasons(
    items: List[Dict[str, Any]],
    *, 
    seed_title: Optional[str] = None,
    freshness_years: int = 4,
    min_vote_avg: float = 7.0,
    min_vote_count: int = 500,
    trending_ids: Optional[Iterable[int]] = None,
) -> List[Dict[str, Any]]:
    """Attach small, human-readable 'why this' reasons to each item.
    This is non-blocking and safe to run after scoring/filters.
    Expected item fields if available: title/name, first_air_date/year, vote_average, vote_count,
    debug_reasons (will be created if missing), id/tmdb_id/tmdbId.
    """
    now_year = datetime.utcnow().year
    trending_ids = set(int(x) for x in (trending_ids or []))

    def _id(it): 
        return it.get("id") or it.get("tmdb_id") or it.get("tmdbId") or it.get("tmdbID")

    for it in items:
        reasons = it.get("debug_reasons")
        if not isinstance(reasons, list):
            reasons = []
            it["debug_reasons"] = reasons

        # Freshness
        year = None
        if isinstance(it.get("first_air_date"), str) and len(it["first_air_date"]) >= 4:
            try:
                year = int(it["first_air_date"][0:4])
            except Exception:
                year = None
        elif it.get("year"):
            try:
                year = int(it["year"])
            except Exception:
                year = None
        if year and (now_year - year) <= freshness_years:
            reasons.append("Newer series")  # keep short for chips

        # Ratings
        va = _as_float(it.get("vote_average"), 0.0)
        vc = int(_as_float(it.get("vote_count"), 0))
        if va >= min_vote_avg and vc >= min_vote_count:
            reasons.append("High rating")

        # Trending
        try:
            tid = int(_id(it) or 0)
            if tid in trending_ids:
                reasons.append("Trending now")
        except Exception:
            pass

        # Seed adjacency (title only)
        if seed_title:
            reasons.append(f"Similar to {seed_title}")

        # Keep to max 3 reasons
        if len(reasons) > 3:
            it["debug_reasons"] = reasons[:3]

    return items
