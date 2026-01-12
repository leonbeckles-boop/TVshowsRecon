# app/routes/reclogs.py
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, Boolean, Text, DateTime, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, get_async_db
from app.security import require_user

router = APIRouter(prefix="/recs", tags=["Feedback / Logs"])

# ──────────────────────────────────────────────────────────────────────────────
# ORM model (kept here for convenience so it's created automatically on startup)
# ──────────────────────────────────────────────────────────────────────────────

class RecFeedback(Base):
    """
    Minimal feedback record:
      - user_id    : who gave feedback (JWT-protected)
      - show_id    : the recommended show's internal ID (or TMDb id if you use that)
      - useful     : thumbs up/down
      - notes      : optional free text (<= 2000 chars)
    """
    __tablename__ = "rec_feedback"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    show_id = Column(Integer, index=True, nullable=False)
    useful = Column(Boolean, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────

class FeedbackIn(BaseModel):
    show_id: int = Field(..., ge=1, description="Internal show_id (or TMDb id if that's what you store)")
    useful: bool
    notes: Optional[str] = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: int
    user_id: int
    show_id: int
    useful: bool
    notes: Optional[str] = None
    created_at: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Routes (secured with require_user so only the owner can write/read)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/{user_id}/feedback")
async def create_feedback(
    user_id: int,
    payload: FeedbackIn,
    _: Any = Depends(require_user),  # ✅ ensures JWT sub === user_id
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    rec = RecFeedback(
        user_id=user_id,
        show_id=payload.show_id,
        useful=payload.useful,
        notes=payload.notes,
    )
    db.add(rec)
    await db.commit()
    return {"ok": True}


@router.get("/{user_id}/feedback", response_model=List[FeedbackOut])
async def list_feedback(
    user_id: int,
    limit: int = Query(50, ge=1, le=500),
    _: Any = Depends(require_user),  # ✅ same ownership check
    db: AsyncSession = Depends(get_async_db),
):
    rows = (
        await db.execute(
            select(RecFeedback)
            .where(RecFeedback.user_id == user_id)
            .order_by(RecFeedback.id.desc())
            .limit(limit)
        )
    ).scalars().all()

    return [
        FeedbackOut(
            id=r.id,
            user_id=r.user_id,
            show_id=r.show_id,
            useful=r.useful,
            notes=r.notes,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
