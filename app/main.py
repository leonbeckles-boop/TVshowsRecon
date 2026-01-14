from __future__ import annotations
import logging
from typing import Dict, Any, List

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

# ───────────────── CORS (Vercel + local) ─────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://t-vshows-recon.vercel.app",
    ],
    allow_origin_regex=r"^https:\/\/t-vshows-recon-.*\.vercel\.app$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────── Health / Debug ─────────────────
@app.get("/api/health", tags=["default"])
async def health() -> Dict[str, Any]:
    return {"ok": True}

@app.get("/api/_debug/routes", tags=["default"])
async def list_routes() -> List[Dict[str, Any]]:
    return [
        {
            "path": r.path,
            "methods": sorted(getattr(r, "methods", []) or []),
            "name": getattr(r, "name", ""),
        }
        for r in app.routes
    ]


# ───────────────── API Router ─────────────────
api = APIRouter(prefix="/api")

# ───────────────── Explicit router imports ─────────────────
# IMPORTANT: these imports MUST match real files

from app.routes.recs_v3 import router as recs_v3_router
from app.routes.discover import router as discover_router
from app.routes.library import router as library_router
from app.routes.ratings import router as ratings_router
from app.routes.users import router as users_router
from app.routes.shows import router as shows_router
from app.routes.auth import router as auth_router
from app.routes.admin_reddit import router as admin_reddit_router
from app.routes.not_interested import router as not_interested_router
from app.routes.wrapped import router as wrapped_router
from app.routes.admin import router as admin_router

# 🔴 THIS is the missing one
from app.routes.tmdb import router as tmdb_router


# ───────────────── Mount routers ─────────────────
api.include_router(recs_v3_router)
api.include_router(discover_router)
api.include_router(library_router)
api.include_router(ratings_router)
api.include_router(users_router)
api.include_router(shows_router)
api.include_router(tmdb_router)          # ✅ FIX
api.include_router(auth_router)
api.include_router(admin_reddit_router)
api.include_router(not_interested_router)
api.include_router(wrapped_router)
api.include_router(admin_router)

app.include_router(api)
