import httpx
from typing import Any, Dict, List, Optional
from app.core.settings import settings

class TMDBClient:
    def __init__(self, api_key: str, base: str = "https://api.themoviedb.org/3"):
        self.api_key = api_key
        self.base = base

    async def search_tv(self, q: str, page: int = 1) -> Dict[str, Any]:
        params = {"query": q, "page": page, "api_key": self.api_key}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{self.base}/search/tv", params=params)
            r.raise_for_status()
            return r.json()

    async def tv_detail(self, tv_id: int, append: Optional[List[str]] = None) -> Dict[str, Any]:
        params = {"api_key": self.api_key}
        if append:
            params["append_to_response"] = ",".join(append)
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{self.base}/tv/{tv_id}", params=params)
            r.raise_for_status()
            return r.json()

    async def similar_tv(self, tv_id: int, page: int = 1) -> List[Dict[str, Any]]:
        params = {"api_key": self.api_key, "page": page}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{self.base}/tv/{tv_id}/similar", params=params)
            r.raise_for_status()
            data = r.json()
            return data.get("results", [])

tmdb_client = TMDBClient(api_key=settings.tmdb_api_key or "")
