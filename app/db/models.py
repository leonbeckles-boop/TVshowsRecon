# app/db/models.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, UniqueConstraint, func

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    favorites_tmdb: Mapped[list["FavoriteTMDB"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ratings: Mapped[list["UserRating"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

class FavoriteTMDB(Base):
    __tablename__ = "favorites_tmdb"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, index=True)

    user: Mapped["User"] = relationship(back_populates="favorites_tmdb")

    __table_args__ = (UniqueConstraint("user_id", "tmdb_id", name="uq_user_tmdb"),)

class UserRating(Base):
    __tablename__ = "user_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rating: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0–10.0
    watched_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    seasons_completed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    user: Mapped["User"] = relationship(back_populates="ratings")

    __table_args__ = (UniqueConstraint("user_id", "tmdb_id", name="uq_user_rating"),)
