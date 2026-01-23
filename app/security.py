# app/security.py
from __future__ import annotations

from fastapi import Depends, HTTPException, Path
from app.routes.auth import get_current_user
from app.models_auth import AuthUser


def require_user(
    current: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """
    Auth-only dependency.
    Use for routes WITHOUT a {user_id} in the path.
    """
    return current


def require_user_match(
    user_id: int = Path(..., ge=1),
    current: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """
    Guard for routes WITH a {user_id} path parameter.
    Ensures the JWT subject matches the requested user_id.
    """
    if current.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return current
