# app/db_models.py
from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Text,
    Float,
    func,
)

# CRITICAL: import Base from models_auth so ALL tables share the same MetaData
from app.models_auth import Base


# ----------------------------
# Core catalogue
# ----------------------------
class Show(Base):
    """
    Local TV show record.
    NOTE: Primary key is show_id (not 'id').
    """
    __tablename__ = "shows"

    show_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    title = Column(String(300), nullable=False, index=True)
    year = Column(Integer, nullable=True)
    poster_url = Column(String(500), nullable=True)

    # NEW: canonical TMDb TV id as integer
    tmdb_id = Column(Integer, nullable=True, unique=True, index=True)

    # Legacy: old string TMDb id (used before migration). Safe to keep for now.
    # Can be dropped later once everything is on tmdb_id.
    external_id = Column(String(50), nullable=True, index=True)



class RedditPost(Base):
    """
    Posts ingested from Reddit and optionally linked to a show.
    """
    __tablename__ = "reddit_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reddit_id = Column(String(32), unique=True, index=True)

    # NOTE: FK points to shows.show_id (matches Show PK name)
    show_id = Column(
        Integer,
        ForeignKey("shows.show_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    score = Column(Integer, nullable=True)
    subreddit = Column(String(200), nullable=True)
    created_utc = Column(DateTime(timezone=True), nullable=True, index=True)


# ----------------------------
# Favorites / Ratings / Not Interested (TMDb-keyed)
# ----------------------------
class FavoriteTmdb(Base):
    """
    A user's favorites keyed by TMDb TV id.
    No FK to `shows` so users can favorite items not yet in local catalogue.
    """
    __tablename__ = "user_favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # IMPORTANT: FK points to auth_users.id (this is what we actually create)
    user_id = Column(Integer, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    tmdb_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "tmdb_id", name="uq_user_fav_user_tmdb"),
    )


class Rating(Base):
    """
    A user's rating for a TMDb TV id (0..10).
    """
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    tmdb_id = Column(Integer, nullable=False, index=True)

    rating = Column(Float, nullable=False)
    title = Column(String(300), nullable=True)
    seasons_completed = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "tmdb_id", name="uq_rating_user_tmdb"),
    )


# Back-compat: some modules import UserRating; keep alias
UserRating = Rating


class NotInterested(Base):
    """
    A list of TMDb ids the user does not want in recommendations.
    """
    __tablename__ = "not_interested"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    tmdb_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "tmdb_id", name="uq_not_interested_user_tmdb"),
    )


__all__ = [
    "Base",
    "Show",
    "RedditPost",
    "FavoriteTmdb",
    "Rating",
    "UserRating",
    "NotInterested",
]
