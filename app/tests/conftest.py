# app/tests/conftest.py
import pytest
import fakeredis.aioredis

@pytest.fixture(autouse=True)
async def fake_app_cache(monkeypatch):
    """
    Ensure app.infra.cache uses a FakeRedis client in tests.
    Works whether your code accesses app.infra.cache._redis directly
    or calls cache.init(...) which uses redis.asyncio.from_url().
    """
    # Create a single FakeRedis instance per test
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    # 1) Force the module-level _redis handle
    import app.infra.cache as app_cache
    monkeypatch.setattr(app_cache, "_redis", fake, raising=True)

    # 2) If code calls cache.init(url) internally, make from_url return fake
    import redis.asyncio as redis_asyncio
    monkeypatch.setattr(redis_asyncio, "from_url", lambda *a, **k: fake, raising=True)

    try:
        yield
    finally:
        await fake.aclose()

