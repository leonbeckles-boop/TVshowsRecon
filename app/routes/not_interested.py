# app/routes/not_interested.py
from __future__ import annotations
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.security import require_user
from app.db_models import NotInterested  # added in step 1

router = APIRouter(prefix="/users", tags=["Not Interested"])

class HiddenOut(BaseModel):
    tmdb_id: int

@router.get("/{user_id}/not-interested", response_model=List[HiddenOut])
async def list_not_interested(
    user_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
):
    rows = (await db.execute(
        select(NotInterested.tmdb_id).where(NotInterested.user_id == user_id)
    )).scalars().all()
    return [HiddenOut(tmdb_id=int(x)) for x in rows]

@router.post("/{user_id}/not-interested/{tmdb_id}", status_code=201)
async def add_not_interested(
    user_id: int = Path(..., ge=1),
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
):
    # upsert-ish: if exists, do nothing (idempotent)
    exists = (await db.execute(
        select(NotInterested).where(
            NotInterested.user_id == user_id,
            NotInterested.tmdb_id == tmdb_id
        )
    )).scalar_one_or_none()
    if exists:
        return {"ok": True}
    db.add(NotInterested(user_id=user_id, tmdb_id=tmdb_id))
    await db.commit()
    return {"ok": True}

@router.delete("/{user_id}/not-interested/{tmdb_id}", status_code=204)
async def remove_not_interested(
    user_id: int = Path(..., ge=1),
    tmdb_id: int = Path(..., ge=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
):
    await db.execute(
        delete(NotInterested).where(
            NotInterested.user_id == user_id,
            NotInterested.tmdb_id == tmdb_id,
        )
    )
    await db.commit()
