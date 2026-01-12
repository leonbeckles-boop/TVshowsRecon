# app/infra/cache.py
from __future__ import annotations

import json
import os
from typing import Any, Optional

import redis.asyncio as redis

_redis: Optional[redis.Redis] = None


def init(url: str) -> None:
    """Synchronous init. Stores a global Redis client."""
    global _redis
    _redis = redis.from_url(url, decode_responses=True)


def is_ready() -> bool:
    return _redis is not None


def client() -> redis.Redis:
    """
    Return a Redis client. If not initialized, try lazy init from REDIS_URL
    to avoid hard crashes during app startup races.
    """
    global _redis
    if _redis is None:
        url = os.getenv("REDIS_URL")
        if url:
            init(url)
        else:
            raise RuntimeError(
                "Redis cache not initialized and REDIS_URL not set. "
                "Set REDIS_URL or call cache.init(REDIS_URL) on startup."
            )
    return _redis  # type: ignore[return-value]


async def get_json(key: str) -> Any:
    c = client()
    val = await c.get(key)
    if val is None:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None


async def set_json(key: str, value: Any, ttl: int = 3600) -> None:
    c = client()
    try:
        data = json.dumps(value, ensure_ascii=False)
    except Exception:
        # last resort: store str(value)
        data = str(value)
    await c.set(key, data, ex=ttl)
