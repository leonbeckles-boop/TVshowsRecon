# app/main.py — robust router mounting + correct CORS for Vercel + better diagnostics

from __future__ import annotations

import logging
import traceback
from typing import List, Dict, Any

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

log = logging.getLogger("startup")

app = FastAPI(
    title="TVshowsRecon API",
    version="1.0.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)

# ───────────────── CORS ─────────────────
# You are using Bearer tokens (Authorization header), not cookies,
# so allow_credentials should be False.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://t-vshows-recon.vercel.app",
    ],
    # Allow all Vercel preview deploy URLs for this project:
    allow_origin_regex=r"^https:\/\/t-vshows-recon-.*\.vercel\.app$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────── Health & route debug ─────────────────
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

# Single API namespace prefix
api = APIRouter(prefix="/api")


def _include(router_import: str, attr: str = "router", *, name_hint: str = "") -> None:
    """
    Import a router lazily and include it.
    If missing/broken, we log FULL traceback so the Render logs tell us exactly why.
    """
    label = name_hint or router_import
    try:
        mod = __import__(router_import, fromlist=[attr])
        router = getattr(mod, attr)
        api.include_router(router)
        log.info("Mounted router: %s (prefix=%s)", label, getattr(router, "prefix", ""))
    except Exception as e:
        tb = traceback.format_exc()
        log.error("FAILED to mount router: %s (%s)", label, router_import)
        log.error("Reason: %r", e)
        log.error("Traceback:\n%s", tb)


# ───────────────── Mount routers (no /api duplication) ─────────────────
_include("app.routes.recs_v3", name_hint="recs_v3")
_include("app.routes.discover", name_hint="discover")
_include("app.routes.library", name_hint="library")
_include("app.routes.ratings", name_hint="ratings")
_include("app.routes.users", name_hint="users")
_include("app.routes.shows", name_hint="shows")
_include("app.routes.tmdb", name_hint="tmdb")            # <-- should mount /api/tmdb/*
_include("app.routes.auth", name_hint="auth")
_include("app.routes.admin_reddit", name_hint="admin_reddit")
_include("app.routes.not_interested", name_hint="not_interested")
_include("app.routes.wrapped", name_hint="wrapped")
_include("app.routes.admin", name_hint="admin")

# Attach /api router once
# Attach /api router once
app.include_router(api, prefix="/api")

