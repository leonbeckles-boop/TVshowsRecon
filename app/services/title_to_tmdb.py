
import os
import asyncio
from typing import Optional, Dict, Any, List
import httpx

_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
LOCAL_TMDB_SEARCH = os.getenv("LOCAL_TMDB_SEARCH", "http://localhost:8000/api/tmdb/search")
USER_AGENT = os.getenv("REDDIT_USER_AGENT", "tvrecs/0.1")

def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import threading
        res, err = [], []
        def runner():
            try:
                res.append(asyncio.run(coro))
            except Exception as e:
                err.append(e)
        t = threading.Thread(target=runner, daemon=True)
        t.start(); t.join()
        if err:
            raise err[0]
        return res[0]
    else:
        return asyncio.run(coro)

async def resolve_title_to_tmdb(title: str) -> Optional[Dict[str, Any]]:
    title = (title or "").strip()
    if not title:
        return None
    # local proxy first
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as c:
            r = await c.get(LOCAL_TMDB_SEARCH, params={"q": title, "limit": 10})
            if r.status_code == 200:
                data = r.json() or {}
                results: List[Dict[str, Any]] = data.get("results", [])
                if results:
                    for it in results:
                        nm = (it.get("name") or it.get("title") or "").strip()
                        if nm.lower() == title.lower():
                            return it
                    return results[0]
    except Exception:
        pass
    # fallback TMDB
    if TMDB_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as c:
                r = await c.get("https://api.themoviedb.org/3/search/tv", params={
                    "api_key": TMDB_API_KEY,
                    "query": title,
                    "include_adult": "false",
                    "page": 1,
                })
                if r.status_code == 200:
                    data = r.json() or {}
                    res = data.get("results") or []
                    if res:
                        for it in res:
                            nm = (it.get("name") or it.get("title") or "").strip()
                            if nm.lower() == title.lower():
                                return it
                        return res[0]
        except Exception:
            pass
    return None

def resolve_title_to_tmdb_sync(title: str) -> Optional[Dict[str, Any]]:
    key = (title or "").strip().lower()
    if not key:
        return None
    if key in _CACHE:
        return _CACHE[key]
    val = _run_async(resolve_title_to_tmdb(title))
    _CACHE[key] = val
    return val

def lookup_tmdb_id(title: str) -> Optional[int]:
    hit = resolve_title_to_tmdb_sync(title)
    if not hit:
        return None
    try:
        return int(hit.get("id"))
    except Exception:
        return None
