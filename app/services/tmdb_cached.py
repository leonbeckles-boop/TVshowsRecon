# app/services/tmdb_cached.py
from __future__ import annotations
from typing import Any, Dict, List

from app.services import tmdb

# We import infra.cache but never crash if it can't be used.
def _have_cache():
    try:
        from app.infra import cache
        return cache
    except Exception:
        return None


async def get_similar_shows_cached(seed_tmdb_id: int, max_items: int = 20) -> List[Dict[str, Any]]:
    cache = _have_cache()
    ckey = f"tmdb:tv:{int(seed_tmdb_id)}:similar:{int(max_items)}"

    # Try cache read
    if cache is not None:
        try:
            val = await cache.get_json(ckey)
            if val:
                return val
        except Exception:
            # cache not ready / network hiccup → just fall through to direct
            pass

    # Direct TMDb fetch
    data = await tmdb.get_similar_shows(int(seed_tmdb_id), max_items=max_items)

    # Best-effort cache write
    if cache is not None and data:
        try:
            await cache.set_json(ckey, data, ttl=3600)
        except Exception:
            pass

    return data
