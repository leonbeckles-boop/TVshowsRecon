import time
from typing import Any, Dict, Optional
import httpx
import os

# Simple OAuth2 client-credentials flow, no pydantic dependency here
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID") or os.getenv("REDDIT_ID") or ""
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET") or os.getenv("REDDIT_SECRET") or ""
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT") or "tvrecs/0.1 by unknown"

class RedditAuth:
    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._exp: float = 0.0

    async def token(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": REDDIT_USER_AGENT}) as client:
            r = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            )
            r.raise_for_status()
            data = r.json()
            self._token = data["access_token"]
            self._exp = time.time() + float(data.get("expires_in", 3600))
            return self._token

_auth = RedditAuth()

class RedditClient:
    base = "https://oauth.reddit.com"

    async def _headers(self) -> Dict[str, str]:
        tok = await _auth.token()
        return {"Authorization": f"bearer {tok}", "User-Agent": REDDIT_USER_AGENT}

    async def subreddit_top(self, subreddit: str, t: str = "month", limit: int = 50) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20, headers=await self._headers()) as client:
            r = await client.get(f"{self.base}/r/{subreddit}/top", params={"t": t, "limit": limit})
            r.raise_for_status()
            return r.json()
