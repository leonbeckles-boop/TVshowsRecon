# app/security.py
from __future__ import annotations
from fastapi import Depends, HTTPException, Path
from app.routes.auth import get_current_user
from app.models_auth import AuthUser

def require_user(
    user_id: int = Path(..., ge=1),
    current: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """
    Guard dependency for routes with a {user_id} path parameter.
    Ensures the JWT subject matches the requested user_id.
    """
    if current.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return current
