from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "tvrecs/1.0")
REDDIT_SUBS = os.getenv("REDDIT_SUBS", "televisionsuggestions").split(",")

INTERNAL_BASE = os.getenv("INTERNAL_BASE_URL", "http://127.0.0.1:8000")

async def _reddit_token() -> str:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(REDDIT_CLIENT_ID, REDDIT_SECRET),
            headers={"User-Agent": REDDIT_USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()
        return data["access_token"]

async def fetch_top_week(token: str, sub: str, limit: int = 100) -> List[Dict[str, Any]]:
    url = f"https://oauth.reddit.com/r/{sub}/top"
    params = {"t": "week", "limit": str(limit)}
    async with httpx.AsyncClient(timeout=30.0, headers={"Authorization": f"bearer {token}", "User-Agent": REDDIT_USER_AGENT}) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        js = r.json()
        items = [it["data"] for it in (js.get("data", {}).get("children") or []) if isinstance(it, dict) and "data" in it]
        return items

async def fetch_search_for_titles(token: str, sub: str, titles: List[str], per_title: int = 30) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not titles:
        return out

    async with httpx.AsyncClient(timeout=30.0, headers={"Authorization": f"bearer {token}", "User-Agent": REDDIT_USER_AGENT}) as client:
        for t in titles[:20]:
            q = f'title:"{t}"'
            url = f"https://oauth.reddit.com/r/{sub}/search"
            params = {"q": q, "restrict_sr": "true", "sort": "top", "t": "year", "limit": str(per_title)}
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                js = r.json()
                items = [it["data"] for it in (js.get("data", {}).get("children") or []) if isinstance(it, dict) and "data" in it]
                out.extend(items)
            except Exception as e:
                logger.warning("reddit_ingest: search failed for %r in r/%s: %s", t, sub, e)
    return out

async def get_user_favourites_titles(user_id: int) -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{INTERNAL_BASE}/api/library/{user_id}/favorites")
            r.raise_for_status()
            js = r.json()
            items = js if isinstance(js, list) else (js.get("items") if isinstance(js, dict) else [])
            titles: List[str] = []
            for it in items:
                name = it.get("title") or it.get("name")
                if isinstance(name, str) and name.strip():
                    titles.append(name.strip())
            return titles
    except Exception as e:
        logger.warning("reddit_ingest: unable to fetch favourites for user %s: %s", user_id, e)
        return []

async def run_ingest(user_id: Optional[int] = None) -> Dict[str, Any]:
    token = await _reddit_token()

    all_items: List[Dict[str, Any]] = []
    for sub in REDDIT_SUBS:
        try:
            all_items.extend(await fetch_top_week(token, sub.strip(), limit=100))
        except Exception as e:
            logger.warning("reddit_ingest: top-week fetch failed for r/%s: %s", sub, e)

    fav_titles: List[str] = []
    if user_id is not None:
        fav_titles = await get_user_favourites_titles(user_id)
        if fav_titles:
            for sub in REDDIT_SUBS:
                more = await fetch_search_for_titles(token, sub.strip(), fav_titles, per_title=15)
                all_items.extend(more)

    saved = 0
    updated = 0
    failed = 0

    logger.info("[Reddit] Ingest complete. user_id=%s fetched=%s saved=%s updated=%s failed=%s",
                user_id, len(all_items), saved, updated, failed)
    return {"fetched": len(all_items), "saved": saved, "updated": updated, "failed": failed}
