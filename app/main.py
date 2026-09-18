import os
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from redis.asyncio import Redis
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter

# Routers
from app.routes import auth, tmdb, discover, ratings, users, shows, not_interested
from app.routes import recs_v3
from app.routes import recs_v4
from app.routes import admin, wrapped
from app.routes import watchlist
from app.routes import seo
from app.routes import seo_html
from app.routes import seo_index
from app.routes import sitemap
from app.routes import admin_tasks


log = logging.getLogger("uvicorn.error")


def _cors_origins() -> list[str]:
    """
    Read allowed CORS origins from env, falling back to sensible defaults.
    Set in Render as:
      CORS_ORIGINS=https://your-frontend.vercel.app,http://localhost:5173
    """
    raw = (os.getenv("CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]

    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

    app.state.tmdb_client = httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        headers={"Accept": "application/json"},
        http2=False,
    )

    redis_url = (
        os.getenv("REDIS_URL")
        or os.getenv("RENDER_REDIS_URL")
        or os.getenv("CACHE_REDIS_URL")
        or "redis://redis:6379/0"
    )
    app.state.redis_client = None

    try:
        redis_client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=False)
        await redis_client.ping()
        FastAPICache.init(RedisBackend(redis_client), prefix="tvrecs-cache")
        app.state.redis_client = redis_client
        log.info("Redis cache initialised")
    except Exception as exc:
        log.warning("Redis cache unavailable; continuing without cache: %r", exc)

    try:
        yield
    finally:
        try:
            await app.state.tmdb_client.aclose()
        except Exception:
            pass
        try:
            if app.state.redis_client is not None:
                await app.state.redis_client.aclose()
        except Exception:
            pass


app = FastAPI(title="WhatNext API", lifespan=lifespan)

cors_origins = _cors_origins() or []

dev_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

cors_origins = list(set(cors_origins + dev_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, Any]:
    return {"ok": True, "service": "whatnext-api"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/_debug/routes")
def list_routes() -> list[dict[str, Any]]:
    out = []
    for r in app.router.routes:
        try:
            methods = sorted(list(getattr(r, "methods", []) or []))
            out.append({"path": getattr(r, "path", ""), "methods": methods, "name": getattr(r, "name", "")})
        except Exception:
            continue
    return out


# -----------------------------
# API router mount
# -----------------------------
api = APIRouter(prefix="/api")

api.include_router(auth.router)
api.include_router(tmdb.router)
api.include_router(discover.router)
api.include_router(ratings.router)
api.include_router(users.router)
api.include_router(shows.router)
api.include_router(recs_v3.router)
api.include_router(recs_v4.router)
api.include_router(admin.router)
api.include_router(wrapped.router)
api.include_router(not_interested.router)
api.include_router(watchlist.router)
api.include_router(admin_tasks.router)

app.include_router(seo.router)
app.include_router(seo_html.router)
app.include_router(seo_index.router)
app.include_router(sitemap.router)

app.include_router(api)