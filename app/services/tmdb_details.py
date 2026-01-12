# app/services/tmdb_details.py
import os
import httpx
from app.infra import cache  # your Redis helper

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

async def get_tv_details(tmdb_id: int) -> dict | None:
    if not TMDB_API_KEY:
        return None
    key = f"tmdb:tv:{tmdb_id}"
    cached = await cache.get_json(key)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://api.themoviedb.org/3/tv/{tmdb_id}",
            params={"api_key": TMDB_API_KEY, "language": "en-US"},
        )
        r.raise_for_status()
        data = r.json()
    await cache.set_json(key, data, ttl=3600)
    return data
