from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, EmailStr, Field


# ── Auth ─────────────────────────────────────────────────────────────────────

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user_id: int
    email: EmailStr


# ── Ratings / Library ────────────────────────────────────────────────────────

class RatingIn(BaseModel):
    tmdb_id: int = Field(gt=0, description="TMDb numeric ID of the show")
    rating: float = Field(ge=0, le=10)
    title: Optional[str] = None
    seasons_completed: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None


class RatingOut(BaseModel):
    tmdb_id: int
    rating: float
    title: Optional[str] = None
    seasons_completed: Optional[int] = None
    notes: Optional[str] = None


class RatingsResponse(BaseModel):
    user_id: int
    ratings: list[RatingOut]


# ── Feedback / Recs logs ─────────────────────────────────────────────────────

class FeedbackIn(BaseModel):
    show_id: int = Field(gt=0, description="Internal show_id (or TMDb id if that's what you store)")
    useful: bool
    notes: Optional[str] = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: int
    user_id: int
    show_id: int
    useful: bool
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# (FastAPI auto-generates ValidationError / HTTPValidationError in OpenAPI;
# no need to re-declare them here for runtime imports.)
