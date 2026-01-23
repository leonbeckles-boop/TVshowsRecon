# app/main.py  — full, safe include of all routers under /api

from __future__ import annotations
import logging
from typing import List, Dict, Any

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


log = logging.getLogger("startup")

app = FastAPI(
    title="TVshowsRecon API",
    version="1.0.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)

# CORS (adjust as you like)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://whatnexttv.vercel.app",   # <-- change to your actual Vercel domain
        "https://*.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ---- Health & route debug ----
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

# The single API namespace prefix. Everything else goes under here.
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

# ---- Mount routers (no /api duplication!) ----
# Each of these router modules should define their OWN local prefix (e.g. "/recs", "/recs/v2", "/auth", etc.)
# Do NOT include "/api" inside those modules.

# v1 recs
#_include("app.routes.recs", name_hint="recs v1")

# v2 recs (diag + wrapper + full)
#_include("app.routes.recs_v2", name_hint="recs v2")
_include("app.routes.recs_v3", name_hint="recs v3")
_include("app.routes.discover", name_hint="discover")

# library/favorites/ratings/users/shows/tmdb/auth/admin (only if present in your repo)
##_include("app.routes.library", name_hint="library")
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

# ---- (Optional) startup tasks kept minimal here; your ensure_schema / reddit boot can live elsewhere ----
# If you need them, re-add with robust error handling, e.g.:
# @app.on_event("startup")
# async def _on_startup():
#     try:
#         from app.db.ensure_schema import ensure_schema
#         from app.db.session import async_engine
#         await ensure_schema(async_engine)
#     except Exception as e:
#         log.error("ensure_schema failed: %s", e)
#     try:
#         from app.services import reddit_scheduler
#         reddit_scheduler.refresh_from_env()  # or a safe no-op if not available
#     except Exception as e:
#         log.warning("Reddit refresh skipped: %s", e)
