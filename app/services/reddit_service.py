# app/services/reddit_service.py
# Updated 2025-10-12
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"
HEADERS = {"User-Agent": "tvrecs/1.0 (by u/yourusername)"}  # set a real UA in production

# Optional OAuth client (preferred if available)
try:
    from app.services.reddit_client import RedditClient
except Exception:
    RedditClient = None  # type: ignore


async def fetch_top_posts(subreddit: str, limit: int = 100, timespan: str = "week") -> List[Dict[str, Any]]:
    """Public JSON API (no OAuth). Fallback if OAuth isn't configured."""
    url = f"{REDDIT_BASE}/r/{subreddit}/top.json?t={timespan}&limit={limit}"
    out: List[Dict[str, Any]] = []
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    logger.warning("[Reddit] r/%s HTTP %s for %s", subreddit, resp.status, url)
                    return out
                data = await resp.json()
                for child in data.get("data", {}).get("children", []):
                    d = child.get("data", {})
                    out.append({
                        "title": d.get("title"),
                        "score": d.get("score"),
                        "num_comments": d.get("num_comments"),
                        "permalink": d.get("permalink"),
                        "subreddit": d.get("subreddit"),
                        "created_utc": d.get("created_utc"),
                    })
    except Exception as e:
        logger.exception("[Reddit] fetch_top_posts failed for r/%s: %s", subreddit, e)
    return out


async def fetch_top_posts_oauth(subreddit: str, limit: int = 100, timespan: str = "week") -> List[Dict[str, Any]]:
    """OAuth-enabled fetch (preferred). Requires RedditClient credentials via env."""
    if not RedditClient:
        return []
    out: List[Dict[str, Any]] = []
    try:
        rc = RedditClient()
        js = await rc.subreddit_top(subreddit, t=timespan, limit=limit)
        for child in js.get("data", {}).get("children", []):
            d = child.get("data", {})
            out.append({
                "title": d.get("title"),
                "score": d.get("score"),
                "num_comments": d.get("num_comments"),
                "permalink": d.get("permalink"),
                "subreddit": d.get("subreddit"),
                "created_utc": d.get("created_utc"),
            })
    except Exception as e:
        logger.exception("[Reddit] fetch_top_posts_oauth failed for r/%s: %s", subreddit, e)
    return out


__all__ = ["fetch_top_posts", "fetch_top_posts_oauth"]
