# app/services/health.py
from __future__ import annotations

from typing import Tuple, Dict, Any, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


# Redis: using redis-py async API
from redis.asyncio import from_url as redis_from_url

# ---------- DB ----------
async def ping_db(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

# ---------- Redis ----------
async def ping_redis(redis_url: str) -> Tuple[bool, Dict[str, Any]]:
    info: Dict[str, Any] = {}
    try:
        r = redis_from_url(redis_url, decode_responses=True)
        pong = await r.ping()
        if pong:
            # Optional tiny INFO fetch (kept small)
            server_info = await r.info(section="server")
            info = {"version": server_info.get("redis_version"), "mode": server_info.get("redis_mode")}
            await r.close()
            return True, info
        await r.close()
        return False, info
    except Exception as e:
        return False, {"error": type(e).__name__}

# ---------- TMDb ----------
async def ping_tmdb(api_key: Optional[str], bearer: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
    """
    Calls /configuration with either api_key or Bearer token.
    """
    if not api_key and not bearer:
        return False, {"error": "missing_api_key"}
    headers = {}
    params = {}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if api_key:
        params["api_key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("https://api.themoviedb.org/3/configuration", headers=headers, params=params)
            ok = resp.status_code == 200
            if ok:
                data = resp.json()
                return True, {"images_base_url": data.get("images", {}).get("base_url")}
            else:
                return False, {"status_code": resp.status_code}
    except Exception as e:
        return False, {"error": type(e).__name__}

# ---------- Reddit (optional) ----------
async def ping_reddit_optional(
    client_id: Optional[str],
    client_secret: Optional[str],
    user_agent: Optional[str],
) -> Tuple[bool, Dict[str, Any]]:
    """
    If creds are present, do a very light OAuth client-credentials flow to get an app token.
    If creds are missing, return ok=False but include reason, so readiness reflects reality clearly.
    """
    if not client_id or not client_secret or not user_agent:
        return False, {"error": "missing_credentials"}

    try:
        auth = (client_id, client_secret)
        headers = {"User-Agent": user_agent}
        data = {"grant_type": "client_credentials", "duration": "temporary"}
        async with httpx.AsyncClient(timeout=5) as client:
            token_resp = await client.post("https://www.reddit.com/api/v1/access_token", auth=auth, data=data, headers=headers)
            if token_resp.status_code != 200:
                return False, {"status_code": token_resp.status_code}
            token = token_resp.json().get("access_token")
            if not token:
                return False, {"error": "no_token"}

            # Probe a super-cheap endpoint using app token (no user scope)
            hdrs = {"Authorization": f"bearer {token}", "User-Agent": user_agent}
            me_resp = await client.get("https://oauth.reddit.com/api/v1/scopes", headers=hdrs)
            return (me_resp.status_code == 200), {"status_code": me_resp.status_code}
    except Exception as e:
        return False, {"error": type(e).__name__}
