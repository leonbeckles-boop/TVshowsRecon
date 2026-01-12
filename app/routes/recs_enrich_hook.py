
"""
app/routes/recs_enrich_hook.py

Drop-in helper to enrich recommendation items with TMDB genre metadata on-the-fly.
It does NOT persist anything to the DB; it only augments the response payload.

Usage inside your existing recs endpoint:

    from app.routes.recs_enrich_hook import enrich_tmdb_genres_for_items

    # after you compute base_candidates and BEFORE your genre filter runs:
    base_candidates, enrich_meta = await enrich_tmdb_genres_for_items(base_candidates)
    meta["genre_enrichment"] = enrich_meta  # optional for debugging

"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

# We assume you already have this service in your codebase
# It should expose: async def get_tv_details(tmdb_id: int) -> dict
from app.services import tmdb_details


def _needs_genres(item: Dict[str, Any]) -> bool:
    # treat both None and empty as "missing"
    if "genre_ids" in item and item.get("genre_ids"):
        return False
    if "genres" in item and item.get("genres"):
        return False
    return True


async def _fetch_one(tmdb_id: int) -> Tuple[int, Dict[str, Any] | None, str | None]:
    """
    Returns (tmdb_id, details_dict_or_none, error_or_none)
    """
    try:
        data = await tmdb_details.get_tv_details(int(tmdb_id))
        return tmdb_id, data, None
    except Exception as e:  # pragma: no cover
        return tmdb_id, None, f"{type(e).__name__}: {e}"


async def enrich_tmdb_genres_for_items(
    items: List[Dict[str, Any]],
    max_concurrency: int = 8,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Given a list of recommendation items (dicts with at least tmdb_id/title),
    fetch TMDB details for those missing genres and attach:
        - item["genre_ids"] = [int, ...]
        - item["genres"]    = [{"id": int, "name": str}, ...]

    Returns: (items, meta)
    meta contains simple debugging stats.
    """
    # Fast path: nothing to do
    missing_ids = [int(it["tmdb_id"]) for it in items if it.get("tmdb_id") and _needs_genres(it)]
    missing_ids = sorted(set(missing_ids))
    if not missing_ids:
        return items, {"enriched": 0, "skipped": len(items), "errors": []}

    # Concurrency control
    sem = asyncio.Semaphore(max_concurrency)

    async def _guarded_fetch(tid: int):
        async with sem:
            return await _fetch_one(tid)

    coros = [_guarded_fetch(tid) for tid in missing_ids]
    results = await asyncio.gather(*coros)

    # Build lookup map
    by_id: Dict[int, Dict[str, Any]] = {}
    errors: List[str] = []
    enriched_count = 0

    for tid, details, err in results:
        if err is not None:
            errors.append(f"{tid}: {err}")
            continue
        if not details:
            continue

        # Expect TMDB payload with "genres": [{"id":..., "name":...}, ...]
        genre_list = details.get("genres") or []
        genre_ids = [int(g.get("id")) for g in genre_list if isinstance(g, dict) and g.get("id") is not None]

        by_id[tid] = {
            "genre_ids": genre_ids,
            "genres": [{"id": int(g.get("id")), "name": str(g.get("name", "")).strip()} for g in genre_list if isinstance(g, dict) and g.get("id") is not None],
        }

    # Apply updates to items in-place
    for it in items:
        tid = it.get("tmdb_id")
        if tid is None:
            continue
        if _needs_genres(it) and int(tid) in by_id:
            it.update(by_id[int(tid)])
            enriched_count += 1

    meta = {
        "requested": len(missing_ids),
        "enriched": enriched_count,
        "skipped": len(items) - enriched_count,
        "errors": errors[:10],  # cap
    }
    return items, meta
