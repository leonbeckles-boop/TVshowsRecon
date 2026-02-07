from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Body, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session


router = APIRouter(prefix="/admin", tags=["admin"])

from fastapi import Depends, HTTPException, status
from app.routes.auth import get_current_user

async def require_admin(user: Any = Depends(get_current_user)) -> Any:
    if not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user

def _get_password_hasher():
    """
    Prefer project's canonical hashing helper if present.
    Falls back to passlib bcrypt (requires passlib[bcrypt]).
    """
    try:
        from app.auth.security import get_password_hash  # type: ignore
        return get_password_hash
    except Exception:
        pass

    try:
        from app.auth.utils import get_password_hash  # type: ignore
        return get_password_hash
    except Exception:
        pass

    try:
        from passlib.context import CryptContext  # type: ignore
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

        def _hash(pw: str) -> str:
            return pwd_context.hash(pw)

        return _hash
    except Exception as e:
        raise RuntimeError(
            "No password hashing function found. "
            "Add app.auth.security.get_password_hash or install passlib[bcrypt]."
        ) from e


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AdminUserOut(BaseModel):
    id: int
    email: EmailStr
    username: Optional[str] = None
    is_admin: bool = False
    created_at: Optional[datetime] = None


class AdminStatsOut(BaseModel):
    total_users: int
    new_users_last_7_days: int
    total_favorites: int
    users_with_favorites: int
    total_ratings: int
    users_with_ratings: int
    total_not_interested: int


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=256)


@router.get("/stats", response_model=AdminStatsOut, dependencies=[Depends(require_admin)])
async def admin_stats(session: AsyncSession = Depends(get_async_session)) -> Any:
    """
    Lightweight admin stats for dashboard.
    Uses SQL for speed and avoids ORM coupling.
    """
    seven_days_ago = _utc_now() - timedelta(days=7)

    q = text(
        """
        WITH users AS (
            SELECT id, created_at
            FROM auth_users
        )
        SELECT
            (SELECT COUNT(*) FROM users)                                      AS total_users,
            (SELECT COUNT(*) FROM users WHERE created_at >= :since)           AS new_users_last_7_days,
            (SELECT COUNT(*) FROM user_favorites)                             AS total_favorites,
            (SELECT COUNT(DISTINCT user_id) FROM user_favorites)              AS users_with_favorites,
            (SELECT COUNT(*) FROM ratings)                                    AS total_ratings,
            (SELECT COUNT(DISTINCT user_id) FROM ratings)                     AS users_with_ratings,
            (SELECT COUNT(*) FROM not_interested)                             AS total_not_interested
        """
    )
    row = (await session.execute(q, {"since": seven_days_ago})).mappings().first()
    if not row:
        return AdminStatsOut(
            total_users=0,
            new_users_last_7_days=0,
            total_favorites=0,
            users_with_favorites=0,
            total_ratings=0,
            users_with_ratings=0,
            total_not_interested=0,
        )
    return AdminStatsOut(**row)


@router.get("/users", response_model=List[AdminUserOut], dependencies=[Depends(require_admin)])
async def admin_list_users(
    q: str = Query("", max_length=200, description="Search by email/username"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """
    List users for admin panel (supports simple search + pagination).
    """
    like = f"%{q.strip()}%" if q and q.strip() else None

    sql = text(
        """
        SELECT id, email, username, is_admin, created_at
        FROM auth_users
        WHERE (:like IS NULL)
           OR (email ILIKE :like)
           OR (username ILIKE :like)
        ORDER BY created_at DESC NULLS LAST, id DESC
        LIMIT :limit
        OFFSET :offset
        """
    )
    rows = (await session.execute(sql, {"like": like, "limit": limit, "offset": offset})).mappings().all()
    return [AdminUserOut(**r) for r in rows]


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
async def admin_delete_user(user_id: int, session: AsyncSession = Depends(get_async_session)) -> Any:
    """
    Deletes a user and associated user-owned rows.
    """
    if user_id == 1 and os.getenv("ADMIN_PROTECT_USER1", "1") == "1":
        raise HTTPException(status_code=400, detail="Primary admin user cannot be deleted")

    exists = (await session.execute(text("SELECT 1 FROM auth_users WHERE id=:id"), {"id": user_id})).first()
    if not exists:
        raise HTTPException(status_code=404, detail="User not found")

    await session.execute(text("DELETE FROM user_favorites WHERE user_id=:id"), {"id": user_id})
    await session.execute(text("DELETE FROM ratings WHERE user_id=:id"), {"id": user_id})
    await session.execute(text("DELETE FROM not_interested WHERE user_id=:id"), {"id": user_id})

    await session.execute(text("DELETE FROM auth_users WHERE id=:id"), {"id": user_id})
    await session.commit()
    return None


@router.post("/users/{user_id}/reset-password", status_code=204, dependencies=[Depends(require_admin)])
async def admin_reset_password(
    user_id: int,
    payload: ResetPasswordIn = Body(...),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """
    Reset a user's password (admin-only).
    """
    row = (await session.execute(text("SELECT id FROM auth_users WHERE id=:id"), {"id": user_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    hash_fn = _get_password_hasher()
    pw_hash = hash_fn(payload.new_password)

    await session.execute(
        text("UPDATE auth_users SET password_hash=:pw, updated_at=:now WHERE id=:id"),
        {"pw": pw_hash, "now": _utc_now(), "id": user_id},
    )
    await session.commit()
    return None
