from fastapi_cache import FastAPICache

async def clear_namespace(namespace: str | None = None):
    """
    Clear everything (or one namespace). fastapi-cache2 >=0.2.2 supports clear().
    """
    backend = FastAPICache.get_backend()
    if namespace:
        # fastapi-cache2 namespaces are just part of the key; clear() nukes all.
        # If you need selective clears, use a pattern delete below:
        await backend.clear()
    else:
        await backend.clear()

async def delete_pattern(pattern: str):
    """
    More selective: delete keys by pattern using the underlying Redis.
    """
    backend = FastAPICache.get_backend()
    r = backend.redis
    # Use SCAN to avoid blocking Redis
    async for key in _ascans(r, pattern):
        await r.delete(key)

async def _ascans(r, pattern: str, count: int = 500):
    cursor = "0"
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=pattern, count=count)
        for k in keys:
            yield k
        if cursor == "0":
            break

async def invalidate_user_recs(user_id: int):
    # Our recs cache keys will include "recs:user:{id}"
    await delete_pattern("tvrecs:*recs:user:%d*" % user_id)
