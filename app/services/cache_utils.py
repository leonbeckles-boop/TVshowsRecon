# app/services/cache_utils.py
from __future__ import annotations

from typing import Iterable
from fastapi_cache import FastAPICache

# You call this from mutating endpoints after favorites/ratings changes.
# Example usage in routes:
#    from app.services.cache_utils import invalidate_user_recs
#    await invalidate_user_recs(user_id)
async def invalidate_user_recs(user_id: int) -> int:
    """
    Invalidate all cached /recs entries for a specific user_id.
    Returns the number of keys deleted.
    """
    backend = FastAPICache.get_backend()
    if backend is None:
        return 0

    # This relies on RedisBackend having `.redis` attr (fastapi-cache2)
    redis = getattr(backend, "redis", None)
    if redis is None:
        return 0

    prefix = FastAPICache.get_prefix() or ""
    # Keys include URL, so match on 'recs' namespace and 'user_id=<id>'
    # Example key looks like: {prefix}recs:<hash or url>...user_id=123...
    patterns: Iterable[str] = (
        f"{prefix}*recs*user_id={user_id}*",
        f"{prefix}*recs*user_id%3D{user_id}*",  # URL-encoded '=' in some builders
    )

    deleted = 0
    for pattern in patterns:
        async for key in redis.scan_iter(pattern):
            deleted += await redis.delete(key)
    return deleted
