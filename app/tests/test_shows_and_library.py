# tests/test_shows_and_library.py
import os
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.main import app
from app.database import async_engine, get_async_db

@pytest.fixture(scope="session", autouse=True)
def _set_env():
    # Use a separate DB if you want; here we rely on your dev DB.
    os.environ.setdefault("ENV", "test")

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://testserver") as ac:
        yield ac

@pytest.mark.asyncio
async def test_health_and_docs(client: AsyncClient):
    r = await client.get("/openapi.json")
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_shows_search_empty_ok(client: AsyncClient):
    r = await client.get("/shows?q=zzzxunlikely")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)

@pytest.mark.asyncio
async def test_library_favorite_and_list(client: AsyncClient):
    # Add favorite for user 1 (Breaking Bad 1396)
    r = await client.post("/library/1/favorites", json={"tmdb_id": 1396})
    assert r.status_code in (200, 201, 409)  # 409 if already exists
    r = await client.get("/library/1/favorites")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

@pytest.mark.asyncio
async def test_ingest_endpoint(client: AsyncClient, monkeypatch):
    # Don’t hit Reddit in tests – stub the service
    from app.services import reddit_ingest

    def fake_ingest_once(limit: int = 50):
        return {"saved": 0, "updated": 0}

    monkeypatch.setattr(reddit_ingest, "ingest_once", fake_ingest_once)
    r = await client.post("/ingest/reddit?limit=5")
    assert r.status_code == 200
    assert r.json()["ok"] is True
