# app/routes/admin.py
from __future__ import annotations

from typing import Any, Dict, Optional, List
import anyio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

# --- Auth / DB imports ---
from app.routes.auth import (
    get_current_user,
    get_db,
    pwd_context,
)
from app.models_auth import AuthUser

# --- DBs & models for Reddit admin ---
# Use the SAME sync session as the ingestor to avoid cross-engine mismatches
from app.database import SessionLocal  # sync session used by ingest
from app.db_models import RedditPost

try:
    from app.services.reddit_ingest import ingest_once as _ingest
except Exception:
    _ingest = None

router = APIRouter(prefix="/admin", tags=["Admin"])


# ───────────────── Admin guard ─────────────────
async def require_admin(user = Depends(get_current_user)):
    if not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# ───────────────── Reddit admin endpoints ─────────────────
@router.post("/reddit/refresh", summary="Refresh Reddit snapshot (ingest)")
async def reddit_refresh(
    limit_posts: int = Query(80, ge=10, le=500),
    subs: Optional[str] = Query(
        None, description="Comma separated subreddits, e.g. televisionsuggestions,netflix"
    ),
    timespan: str = Query("month", regex="^(hour|day|week|month|year|all)$"),
    _admin: Any = Depends(require_admin),
) -> Dict[str, Any]:
    if _ingest is None:
        raise HTTPException(
            status_code=503, detail="reddit_ingest not importable in this build"
        )
    try:
        subs_list: Optional[List[str]] = None
        if subs:
            subs_list = [s.strip() for s in subs.split(",") if s.strip()]
        result = await anyio.to_thread.run_sync(
            _ingest, limit_posts, subs_list, timespan
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"reddit refresh failed: {e}")
    return {"ok": bool(result), "result": result}


@router.get("/reddit/status", summary="Status of Reddit snapshot")
async def reddit_status(_admin: Any = Depends(require_admin)) -> Dict[str, Any]:
    """
    Count rows using the SAME sync SessionLocal as ingest.
    Returns both ORM and RAW counts to avoid mapping/metadata surprises.
    """

    def _read_status_sync() -> Dict[str, Any]:
        with SessionLocal() as db:
            count_orm = 0
            count_raw = 0
            last_epoch: Optional[float] = None

            # ORM first
            try:
                count_orm = int(
                    db.execute(
                        select(func.count()).select_from(RedditPost)
                    ).scalar_one()
                    or 0
                )
            except Exception:
                count_orm = 0

            # Raw fallback — adjust table name if your model uses a different one
            try:
                count_raw = int(
                    db.execute(text("SELECT COUNT(*) FROM reddit_posts")).scalar_one()
                    or 0
                )
            except Exception:
                count_raw = 0

            # best-effort last refresh from common columns
            for col_name in (
                "created_utc",
                "created_at",
                "ingested_at",
                "updated_at",
            ):
                col = getattr(RedditPost, col_name, None)
                if col is None:
                    continue
                try:
                    val = db.execute(select(func.max(col))).scalar_one()
                    if val:
                        if hasattr(val, "timestamp"):
                            last_epoch = float(val.timestamp())
                        elif isinstance(val, (int, float)):
                            last_epoch = float(val)
                        break
                except Exception:
                    pass

            # prefer ORM count if non-zero, else raw
            sample = count_orm or count_raw
            return {
                "last_refresh_epoch": last_epoch,
                "has_snapshot": bool(sample > 0),
                "sample_size": int(sample),
                "debug": {"count_orm": count_orm, "count_raw": count_raw},
            }

    return await anyio.to_thread.run_sync(_read_status_sync)


# ───────────────── User management & stats ─────────────────
@router.get("/users", summary="List all users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
):
    res = await db.execute(select(AuthUser))
    users = res.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "created_at": u.created_at,
            "is_admin": getattr(u, "is_admin", False),
        }
        for u in users
    ]


@router.delete("/users/{user_id}", status_code=204, summary="Delete user")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
):
    user = await db.get(AuthUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    return


class ResetPasswordBody(BaseModel):
    new_password: str


@router.post(
    "/users/{user_id}/reset-password",
    summary="Admin: reset user password",
)
async def reset_password(
    user_id: int,
    body: ResetPasswordBody,
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
):
    user = await db.get(AuthUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = pwd_context.hash(body.new_password)
    db.add(user)
    await db.commit()
    return {"detail": "Password updated"}


@router.get("/stats", summary="Basic user analytics")
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
):
    # Total users
    total_users = await db.scalar(select(func.count(AuthUser.id)))

    # New users in last 7 days (new accounts)
    last_7 = datetime.utcnow() - timedelta(days=7)
    new_users = await db.scalar(
        select(func.count(AuthUser.id)).where(AuthUser.created_at >= last_7)
    )

    # Usage from core tables — using raw SQL for simplicity
    total_favorites = await db.scalar(text("SELECT COUNT(*) FROM user_favorites"))
    total_ratings = await db.scalar(text("SELECT COUNT(*) FROM ratings"))
    total_not_interested = await db.scalar(
        text("SELECT COUNT(*) FROM not_interested")
    )

    users_with_favorites = await db.scalar(
        text("SELECT COUNT(DISTINCT user_id) FROM user_favorites")
    )
    users_with_ratings = await db.scalar(
        text("SELECT COUNT(DISTINCT user_id) FROM ratings")
    )

    return {
        "total_users": int(total_users or 0),
        "new_users_last_7_days": int(new_users or 0),
        "total_favorites": int(total_favorites or 0),
        "total_ratings": int(total_ratings or 0),
        "total_not_interested": int(total_not_interested or 0),
        "users_with_favorites": int(users_with_favorites or 0),
        "users_with_ratings": int(users_with_ratings or 0),
    }
