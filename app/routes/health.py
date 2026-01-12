# app/routes/health.py
from __future__ import annotations

import os
from fastapi import APIRouter
from sqlalchemy import text
from app.database import async_engine  # already in your project

router = APIRouter(tags=["Health"])

# --- simple DB ping ---------------------------------------------------------
async def ping_db() -> bool:
    try:
        async with async_engine.begin() as conn:
            res = await conn.execute(text("SELECT 1"))
            return res.scalar() == 1
    except Exception:
        return False

# --- simple Redis ping (optional; safe if library missing) ------------------
async def ping_redis():
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        import redis.asyncio as redis  # redis-py >= 4.x, async interface
    except Exception:
        return False, {"reason": "redis-py not installed", "url": url}

    try:
        r = redis.from_url(url)
        ok = await r.ping()
        await r.close()
        return bool(ok), {"url": url}
    except Exception as e:
        return False, {"url": url, "error": str(e)}

@router.get("/health", summary="Liveness")
async def health():
    # super cheap liveness (no external deps)
    return {"ok": True}

@router.get("/ready")
async def ready():
    # For now same checks; expand later if needed
    return await health()
