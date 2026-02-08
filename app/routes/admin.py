from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session

# Auth: in this project `get_current_user` lives in app.routes.auth.
# If that import ever moves, update it here to match your project structure.
from app.routes.auth import get_current_user  # type: ignore


router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

async def require_admin(user: Any = Depends(get_current_user)) -> Any:
    """
    Require a valid JWT + an admin user.
    Assumes get_current_user returns an object/dict with `is_admin` and `id`.
    """
    is_admin = getattr(user, "is_admin", None)
    if is_admin is None and isinstance(user, dict):
        is_admin = user.get("is_admin")

    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AdminStatsOut(BaseModel):
    total_users: int
    new_users_last_7_days: int
    total_favorites: int
    users_with_favorites: int
    total_ratings: int
    users_with_ratings: int
    total_not_interested: int


class AdminUserOut(BaseModel):
    id: int
    email: EmailStr
    username: Optional[str] = None
    is_admin: bool = False
    created_at: Optional[datetime] = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """
    Hash a plaintext password using the same scheme as your auth/login flow.

    Option A: Do NOT import bcrypt directly (avoids editor/type-checker complaints
    when bcrypt isn't installed locally). We instead reuse your auth module's
    hasher if available, otherwise fall back to passlib's bcrypt context.
    """
    # 1) Prefer the project's auth helper (keeps compatibility with login)
    try:
        # common pattern
        from app.routes import auth as auth_mod  # type: ignore
        if hasattr(auth_mod, "get_password_hash"):
            return str(auth_mod.get_password_hash(password))  # type: ignore
        if hasattr(auth_mod, "pwd_context"):
            return str(auth_mod.pwd_context.hash(password))  # type: ignore
    except Exception:
        pass

    # 2) Fallback: passlib (bcrypt) without importing `bcrypt` directly
    try:
        from passlib.context import CryptContext  # type: ignore
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return str(ctx.hash(password))
    except Exception as e:
        # If this triggers, install passlib+bcrypt or expose get_password_hash in app.routes.auth
        raise RuntimeError("No password hashing backend available") from e



def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AdminStatsOut, dependencies=[Depends(require_admin)])
async def get_admin_stats(session: AsyncSession = Depends(get_async_session)) -> AdminStatsOut:
    """
    Basic app stats for the Admin dashboard.
    """
    since = _utcnow() - timedelta(days=7)

    # Notes:
    # - auth_users is your user table (as per your router list)
    # - user_favorites / ratings / not_interested are your feature tables
    q = text(
        """
        WITH
          users AS (
            SELECT COUNT(*)::int AS total_users,
                   COUNT(*) FILTER (WHERE created_at >= :since)::int AS new_users_last_7_days
            FROM auth_users
          ),
          favs AS (
            SELECT COUNT(*)::int AS total_favorites,
                   COUNT(DISTINCT user_id)::int AS users_with_favorites
            FROM user_favorites
          ),
          rats AS (
            SELECT COUNT(*)::int AS total_ratings,
                   COUNT(DISTINCT user_id)::int AS users_with_ratings
            FROM ratings
          ),
          ni AS (
            SELECT COUNT(*)::int AS total_not_interested
            FROM not_interested
          )
        SELECT
          users.total_users,
          users.new_users_last_7_days,
          favs.total_favorites,
          favs.users_with_favorites,
          rats.total_ratings,
          rats.users_with_ratings,
          ni.total_not_interested
        FROM users, favs, rats, ni
        """
    )

    row = (await session.execute(q, {"since": since})).mappings().first() or {}
    return AdminStatsOut(**{k: int(row.get(k) or 0) for k in AdminStatsOut.model_fields})


@router.get("/users", response_model=List[AdminUserOut], dependencies=[Depends(require_admin)])
async def admin_list_users(
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, description="Filter by email/username substring"),
) -> List[AdminUserOut]:
    """
    List users (basic fields) for admin management.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    where = ""
    if q:
        where = "WHERE (email ILIKE :q OR username ILIKE :q)"
        params["q"] = f"%{q.strip()}%"

    sql = text(
        f"""
        SELECT id, email, username, is_admin, created_at
        FROM auth_users
        {where}
        ORDER BY created_at DESC NULLS LAST, id DESC
        LIMIT :limit OFFSET :offset
        """
    )

    rows = (await session.execute(sql, params)).mappings().all()
    return [AdminUserOut(**dict(r)) for r in rows]


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
async def admin_delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_async_session),
    admin_user: Any = Depends(require_admin),
) -> None:
    """
    Delete a user and their related rows.
    """
    admin_id = getattr(admin_user, "id", None)
    if admin_id is None and isinstance(admin_user, dict):
        admin_id = admin_user.get("id")

    if admin_id is not None and int(admin_id) == int(user_id):
        raise HTTPException(status_code=400, detail="You cannot delete your own admin account.")

    # Ensure the user exists
    exists = (await session.execute(text("SELECT 1 FROM auth_users WHERE id=:id"), {"id": user_id})).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete dependent rows first (FK-safe even if no FKs exist)
    await session.execute(text("DELETE FROM user_favorites WHERE user_id=:id"), {"id": user_id})
    await session.execute(text("DELETE FROM ratings WHERE user_id=:id"), {"id": user_id})
    await session.execute(text("DELETE FROM not_interested WHERE user_id=:id"), {"id": user_id})

    # Finally delete the user
    await session.execute(text("DELETE FROM auth_users WHERE id=:id"), {"id": user_id})
    await session.commit()
    return None


@router.post("/users/{user_id}/reset-password", status_code=204, dependencies=[Depends(require_admin)])
async def admin_reset_password(
    user_id: int,
    payload: ResetPasswordIn = Body(...),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """
    Set a new password hash for a user.
    Assumes auth_users has a 'hashed_password' column.
    """
    # Ensure user exists
    row = (await session.execute(text("SELECT id FROM auth_users WHERE id=:id"), {"id": user_id})).scalar()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    hashed = _hash_password(payload.new_password)

    res = await session.execute(
        text("UPDATE auth_users SET hashed_password=:hp WHERE id=:id"),
        {"hp": hashed, "id": user_id},
    )
    # Some DB drivers don't expose rowcount reliably; still commit.
    await session.commit()
    return None
