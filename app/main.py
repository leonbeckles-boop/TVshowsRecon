# app/main.py — single FastAPI app, CORS fixed, lifespan client, /api mounted once

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

log = logging.getLogger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reusable TMDB client for the whole app lifetime
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

    app.state.tmdb_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    try:
        yield
    finally:
        await app.state.tmdb_client.aclose()


app = FastAPI(
    title="TVshowsRecon API",
    version="1.0.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# ---- CORS (fixes OPTIONS preflights) ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://whatnexttv.vercel.app",
    ],
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=False,  # keep False for Bearer-token auth
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],  # includes Authorization
    max_age=86400,
)


@app.middleware("http")
async def log_request_time(request: Request, call_next):
    t0 = time.perf_counter()
    resp = await call_next(request)
    dt = (time.perf_counter() - t0) * 1000
    print(
        f"[http] {request.method} {request.url.path}?{request.url.query} -> {resp.status_code} in {dt:.1f}ms"
    )
    return resp


# ---- Health & route debug ----
@app.get("/")
def root():
    return {"status": "ok", "service": "whatnext-api"}


@app.get("/api/health", tags=["default"])
async def health() -> Dict[str, Any]:
    return {"ok": True}


@app.get("/api/_debug/routes", tags=["default"])
async def list_routes() -> List[Dict[str, Any]]:
    out = []
    for r in app.routes:
        methods = sorted(getattr(r, "methods", []) or [])
        out.append({"path": r.path, "methods": methods, "name": getattr(r, "name", "")})
    return out


# ---- /api namespace ----
api = APIRouter(prefix="/api")


def _include(router_import: str, attr: str = "router", *, name_hint: str = "") -> None:
    """Import a router lazily and include it; log but don't crash if missing."""
    try:
        mod = __import__(router_import, fromlist=[attr])
        router = getattr(mod, attr)
        api.include_router(router)
        log.info("Mounted router: %s (%s)", name_hint or router_import, getattr(router, "prefix", ""))
    except Exception as e:
        log.warning("Skipping router %s: %s", name_hint or router_import, e)


# ---- Mount routers (no /api duplication inside the route modules) ----
_include("app.routes.recs_v3", name_hint="recs v3")
_include("app.routes.discover", name_hint="discover")
_include("app.routes.ratings", name_hint="ratings")
_include("app.routes.users", name_hint="users")
_include("app.routes.shows", name_hint="shows")
_include("app.routes.tmdb", name_hint="tmdb")
_include("app.routes.auth", name_hint="auth")
_include("app.routes.admin_reddit", name_hint="admin_reddit")
_include("app.routes.not_interested", name_hint="not_interested")
_include("app.routes.wrapped", name_hint="wrapped")
_include("app.routes.admin", name_hint="admin")

# Attach the /api router once (prevents /api/api duplication)
app.include_router(api)
