# app/schemas.py
from __future__ import annotations

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, ConfigDict


# =========================
# Users & Favorites
# =========================

class User(BaseModel):
    """
    Response model for a user.
    Includes both `username` (preferred) and optional `name`
    for backward compatibility with older routes/clients.
    """
    id: int
    username: str
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    # Optional convenience: a flat list of TMDB ids this user likes
    favorite_tmdb_ids: List[int] = []

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class UserCreate(BaseModel):
    """Payload to create a user."""
    username: str = Field(min_length=1, max_length=64)
    # Optional fields if you capture them at creation time
    name: Optional[str] = None
    email: Optional[EmailStr] = None


class UserUpdate(BaseModel):
    """Payload to update a user."""
    username: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: Optional[str] = None
    email: Optional[EmailStr] = None


class FavoriteAddTMDB(BaseModel):
    """Payload to add a favorite by TMDB id."""
    tmdb_id: int = Field(ge=1)


# =========================
# Ratings
# =========================

class RatingIn(BaseModel):
    tmdb_id: int
    title: Optional[str] = None
    rating: float = Field(ge=0.0, le=10.0)
    watched_at: Optional[datetime] = None
    seasons_completed: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=1000)

    model_config = ConfigDict(from_attributes=True)


class RatingOut(RatingIn):
    id: int


class RatingsList(BaseModel):
    user_id: int
    ratings: List[RatingOut]

    model_config = ConfigDict(from_attributes=True)


# =========================
# Shows (TMDB-shaped details)
# =========================

class Show(BaseModel):
    """
    A general-purpose show descriptor (TMDB-style).
    Use this for client payloads or read models where you surface TMDB info.
    """
    id: int
    name: str
    overview: Optional[str] = None
    first_air_date: Optional[str] = None
    vote_average: Optional[float] = None
    popularity: Optional[float] = None
    genres: Optional[List[dict]] = None
    networks: Optional[List[dict]] = None
    episode_run_time: Optional[List[int]] = None
    poster_path: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
