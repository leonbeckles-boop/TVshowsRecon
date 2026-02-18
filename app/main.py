import os
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter

# Routers
from app.routes import auth, tmdb, discover, ratings, users, shows, not_interested
from app.routes import recs_v3
from app.routes import admin, wrapped
from app.routes import watchlist

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

    # Defaults (safe + practical)
    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        # Add your custom domain here if you have one:
        # "https://whatnext.yourdomain.com",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Shared TMDB client (connection pooling)
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

    app.state.tmdb_client = httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        headers={"Accept": "application/json"},
        http2=False,  # keep False unless you install httpx[http2]
    )

    try:
        yield
    finally:
        try:
            await app.state.tmdb_client.aclose()
        except Exception:
            pass


app = FastAPI(title="WhatNext API", lifespan=lifespan)

# ✅ CORS MUST be installed on `app` (not the APIRouter)
cors_origins = _cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",  # allows preview deploys
    allow_credentials=True,
    allow_methods=["*"],  # includes OPTIONS (preflight)
    allow_headers=["*"],  # includes Authorization, Content-Type, etc.
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
api.include_router(admin.router)
api.include_router(wrapped.router)
api.include_router(not_interested.router)
api.include_router(watchlist.router)

app.include_router(api)
