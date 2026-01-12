# app/services/title_to_tmdb.py
from typing import Optional, Dict
import httpx
from app.core.settings import settings

async def resolve_title_to_tmdb(title: str) -> Optional[Dict]:
    headers = {}
    params = {"query": title, "include_adult": False, "language": "en-US"}
    url = "https://api.themoviedb.org/3/search/tv"

    if settings.tmdb_bearer_token:
        headers["Authorization"] = f"Bearer {settings.tmdb_bearer_token}"
    else:
        params["api_key"] = settings.tmdb_api_key

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        results = r.json().get("results", [])
        return results[0] if results else None
