# app/models_auth.py
from __future__ import annotations

from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, func, Boolean


# IMPORTANT: this Base is imported by app.db_models so all tables share one MetaData
Base = declarative_base()


class AuthUser(Base):
    """
    Authentication / identity table.
    NOTE: Table name is 'auth_users' to match existing DB and FKs.
    """
    __tablename__ = "auth_users"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    # Keep a username field optional; doesn't break routers
    username = Column(String(255), nullable=True)
    # Name is flexible; routers just need *some* hash field
    password_hash = Column(String(255), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_admin = Column(Boolean, nullable=False, server_default="false")
    
    __table_args__ = (
        UniqueConstraint("email", name="uq_auth_users_email"),
    )


__all__ = ["Base", "AuthUser"]
