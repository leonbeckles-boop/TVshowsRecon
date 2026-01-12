
# app/routes/admin_reddit.py
from __future__ import annotations

from typing import Any, Dict, Optional, Callable, List
import importlib
import traceback

from fastapi import APIRouter, BackgroundTasks, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# IMPORTANT: this router's prefix must NOT start with "/api" because main.py mounts it under "/api"
router = APIRouter(prefix="/admin/reddit", tags=["Admin"])

# Central session dependency (works with your app/db/session.py)
try:
    from app.db.session import get_async_session  # type: ignore
except Exception:  # legacy fallback
    from app.session import get_async_session  # type: ignore


def _try_import(paths: List[str]) -> Optional[Any]:
    for p in paths:
        try:
            return importlib.import_module(p)
        except Exception:
            continue
    return None


def _try_call(mod: Any, names: List[str], *args, **kwargs) -> Dict[str, Any]:
    for name in names:
        fn = getattr(mod, name, None)
        if callable(fn):
            try:
                res = fn(*args, **kwargs)
                return {"called": f"{mod.__name__}.{name}", "result": str(res)}
            except Exception as e:
                return {"called": f"{mod.__name__}.{name}", "error": str(e), "trace": traceback.format_exc()}
    return {"error": f"None of {names} found on {getattr(mod, '__name__', mod)}"}


@router.get("/status")
async def reddit_status(session: AsyncSession = Depends(get_async_session)) -> Dict[str, Any]:
    """Count key tables using the same AsyncSession your app uses."""
    counters = {}
    for tbl in ["reddit_posts", "reddit_scores", "reddit_pairs"]:
        try:
            res = await session.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            counters[tbl] = int(res.scalar() or 0)
        except Exception as e:
            counters[tbl] = f"error: {e}"
    return {"ok": True, "counts": counters}


@router.post("/refresh", status_code=202)
async def reddit_refresh(
    bg: BackgroundTasks,
    limit_posts: int = Query(80, ge=10, le=500),
    subs: Optional[str] = Query(None, description="Comma separated list, e.g. televisionsuggestions,netflix"),
    timespan: str = Query("month", pattern="^(hour|day|week|month|year|all)$"),
) -> Dict[str, Any]:
    """Kick off a snapshot refresh. This runs in a background task if possible.
    We try several modules so this works across your variants.
    """
    mod = _try_import([
        "app.services.reddit_service",
        "app.services.reddit_scheduler",
        "app.routes.reddit_ingest",
        "app.reddit_ingest",
    ])
    if not mod:
        return {"detail": "reddit_ingest not importable in this build"}

    def _runner():
        # Try common function names
        calls = _try_call(mod, ["refresh_snapshot", "refresh_from_env", "main", "run"],
                          limit_posts=limit_posts, subs=subs, timespan=timespan)
        return calls

    bg.add_task(_runner)
    return {"queued": True, "note": "Refresh task scheduled."}


@router.post("/ingest_for_user/{user_id}", status_code=202)
async def ingest_for_user(user_id: int, bg: BackgroundTasks) -> Dict[str, Any]:
    """Kick off a personalised ingest for a given user (based on their favorites)."""
    mod = _try_import([
        "app.services.reddit_personal",
        "app.routes.reddit_personal",
        "app.reddit_personal",
    ])
    if not mod:
        return {"detail": "reddit_personal not importable in this build"}

    def _runner():
        return _try_call(mod, ["ingest_for_user", "build_for_user", "main"], user_id=user_id)

    bg.add_task(_runner)
    return {"queued": True, "user_id": user_id, "note": "Personalised ingest queued."}


@router.post("/rebuild_pairs/{user_id}", status_code=202)
async def rebuild_pairs(user_id: int, bg: BackgroundTasks) -> Dict[str, Any]:
    """Recompute personalised pair weights for the user based on latest ingest."""
    mod = _try_import([
        "app.services.user_pairs",
        "app.services.reddit_pairs_from_favs",
        "app.routes.reddit_pairs_from_favs",
        "app.reddit_pairs_from_favs",
    ])
    if not mod:
        return {"detail": "reddit_pairs_from_favs not importable in this build"}

    def _runner():
        return _try_call(mod, ["rebuild_user_pairs", "rebuild_for_user", "main"], user_id=user_id)

    bg.add_task(_runner)
    return {"queued": True, "user_id": user_id, "note": "Rebuild pairs queued."}
