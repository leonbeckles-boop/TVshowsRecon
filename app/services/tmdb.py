# app/services/tmdb.py  (SERVICE MODULE)
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"

def _img(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path:
        return None
    return f"{IMG_BASE}/{size}{path}"

async def _fetch_similar(client: httpx.AsyncClient, tv_id: int, page: int = 1) -> Dict[str, Any]:
    if not TMDB_API_KEY:
        return {"page": 1, "total_pages": 1, "results": []}
    r = await client.get(
        f"{TMDB_BASE}/tv/{tv_id}/similar",
        params={"api_key": TMDB_API_KEY, "language": "en-US", "page": page},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()

def _map_result(r: Dict[str, Any]) -> Dict[str, Any]:
    # Normalize to the shape hybrid expects
    return {
        "id": r.get("id"),
        "title": r.get("name") or r.get("title"),
        "vote_average": r.get("vote_average") or 0.0,
        "popularity": r.get("popularity") or 0.0,
        "poster_url": _img(r.get("poster_path")),
    }

async def get_similar_shows(seed_tmdb_id: int, max_items: int = 20) -> List[Dict[str, Any]]:
    """
    SERVICE function used by app/services/tmdb_cached.py

    Returns up to max_items similar TV shows for the TMDb seed id.
    Each item contains: { id, title, vote_average, popularity, poster_url }
    """
    if max_items <= 0:
        return []

    out: List[Dict[str, Any]] = []

    # Page through results until we have enough
    async with httpx.AsyncClient() as client:
        page = 1
        total_pages = 1
        while len(out) < max_items and page <= total_pages:
            data = await _fetch_similar(client, int(seed_tmdb_id), page=page)
            total_pages = int(data.get("total_pages") or 1)
            for r in data.get("results", []):
                item = _map_result(r)
                # Skip if TMDb didn't provide an id
                if not item.get("id"):
                    continue
                out.append(item)
                if len(out) >= max_items:
                    break
            page += 1

    return out[:max_items]
