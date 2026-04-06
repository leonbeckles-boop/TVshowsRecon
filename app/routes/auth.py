from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, EmailStr, Field

from app.services.onboarding_service import queue_welcome_email
from app.services.email_service import send_email, reset_password_email_html

# ----- DB session dependency: support both names -----
_db_dep: Optional[Callable[..., AsyncSession]] = None
try:
    from app.database import get_async_db as _db_dep  # type: ignore
except Exception:
    try:
        from app.database import get_session as _db_dep  # type: ignore
    except Exception:
        raise RuntimeError("Neither get_async_db nor get_session found in app.database")
get_db = _db_dep  # alias used in Depends()

# ----- User model: support AuthUser or User, and password field name variants -----
try:
    from app.models_auth import AuthUser as UserModel  # type: ignore
except Exception:
    from app.models_auth import User as UserModel  # type: ignore

PWD_FIELD = "password_hash" if hasattr(UserModel, "password_hash") else "hashed_password"

router = APIRouter(prefix="/auth", tags=["auth"])

ALGORITHM = "HS256"
AUTH_SECRET = os.getenv("AUTH_SECRET", "dev_change_me")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200"))  # default 30 days
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "30"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://whatnexttv.org").rstrip("/")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


# -------- Schemas --------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    username: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user_id: int
    email: EmailStr


class MeOut(BaseModel):
    id: int
    email: EmailStr
    username: Optional[str] = None
    is_admin: bool = False


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=6, max_length=128)


# -------- Helpers --------
def _hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def _create_access_token(*, user_id: int, email: str, minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=ALGORITHM)


def _create_password_reset_token(*, user_id: int, email: str, minutes: int = RESET_TOKEN_EXPIRE_MINUTES) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "password_reset",
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=ALGORITHM)


def _decode_password_reset_token(token: str) -> tuple[int, str]:
    try:
        data = jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
        if data.get("type") != "password_reset":
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")

        sub = data.get("sub")
        email = data.get("email")
        if not sub or not email:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")

        return int(sub), str(email)
    except (JWTError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")


async def _user_by_email(session: AsyncSession, email: str) -> Optional[UserModel]:
    res = await session.execute(select(UserModel).where(UserModel.email == email))
    return res.scalar_one_or_none()


# -------- Core auth dependency --------
async def _current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> UserModel:
    if not creds or not creds.scheme or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = creds.credentials
    try:
        data = jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
        sub = data.get("sub")
        email = data.get("email")
        if not sub or not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        user_id = int(sub)
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    res = await session.execute(
        select(UserModel).where(
            UserModel.id == user_id,
            UserModel.email == email,
        )
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


# -------- Back-compat exports --------
async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> UserModel:
    return await _current_user(creds, session)


require_user = get_current_user


# -------- Routes --------
@router.post("/register", response_model=MeOut, status_code=201, summary="Register")
async def register(
    payload: RegisterIn,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> MeOut:
    email_str = str(payload.email)

    if await _user_by_email(session, email_str):
        raise HTTPException(status_code=409, detail="Email already registered")

    user_kwargs = {
        "email": email_str,
        "username": payload.username,
        PWD_FIELD: _hash_password(payload.password),
    }
    user = UserModel(**user_kwargs)  # type: ignore[arg-type]
    session.add(user)

    try:
        await session.commit()
        await session.refresh(user)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    background_tasks.add_task(
        queue_welcome_email,
        user.id,
        user.email,
        getattr(user, "username", None),
    )

    return MeOut(
        id=user.id,
        email=user.email,
        username=getattr(user, "username", None),
        is_admin=getattr(user, "is_admin", False),
    )


@router.post("/login", response_model=TokenOut, summary="Login")
async def login(payload: LoginIn, session: AsyncSession = Depends(get_db)) -> TokenOut:
    email_str = str(payload.email)
    user = await _user_by_email(session, email_str)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    hashed = getattr(user, PWD_FIELD, "")
    if not hashed or not _verify_password(payload.password, hashed):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    await session.execute(
        update(UserModel)
        .where(UserModel.id == user.id)
        .values(last_login_at=datetime.now(timezone.utc))
    )
    await session.commit()

    token = _create_access_token(user_id=user.id, email=user.email)
    return TokenOut(
        access_token=token,
        user_id=user.id,
        email=user.email,
    )


@router.get("/me", response_model=MeOut, summary="Me")
async def me(current: UserModel = Depends(_current_user)) -> MeOut:
    return MeOut(
        id=current.id,
        email=current.email,
        username=getattr(current, "username", None),
        is_admin=getattr(current, "is_admin", False),
    )


@router.post("/touch", summary="Update last seen timestamp")
async def touch(
    current: UserModel = Depends(_current_user),
    session: AsyncSession = Depends(get_db),
):
    await session.execute(
        update(UserModel)
        .where(UserModel.id == current.id)
        .values(last_seen_at=datetime.now(timezone.utc))
    )
    await session.commit()

    return {"ok": True}


@router.post("/password-reset/request", summary="Request password reset")
async def request_password_reset(
    payload: PasswordResetRequestIn,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    email_str = str(payload.email).strip().lower()
    user = await _user_by_email(session, email_str)

    # Always return success so we do not leak whether an email is registered.
    if user:
        token = _create_password_reset_token(user_id=user.id, email=user.email)
        reset_link = f"{FRONTEND_URL}/reset-password?token={token}"
        username = getattr(user, "username", None)

        background_tasks.add_task(
            send_email,
            user.email,
            "Reset your WhatNext password",
            reset_password_email_html(
                reset_link=reset_link,
                first_name=username,
                expiry_minutes=RESET_TOKEN_EXPIRE_MINUTES,
            ),
        )

    return {"ok": True}


@router.post("/password-reset/confirm", summary="Confirm password reset")
async def confirm_password_reset(
    payload: PasswordResetConfirmIn,
    session: AsyncSession = Depends(get_db),
):
    user_id, email = _decode_password_reset_token(payload.token)

    res = await session.execute(
        select(UserModel).where(
            UserModel.id == user_id,
            UserModel.email == email,
        )
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    setattr(user, PWD_FIELD, _hash_password(payload.password))

    await session.execute(
        update(UserModel)
        .where(UserModel.id == user.id)
        .values(last_login_at=datetime.now(timezone.utc))
    )
    await session.commit()

    return {"ok": True}