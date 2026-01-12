# app/routes/ingest.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from typing import Any
from sqlalchemy import select

# Prefer the services path, but fall back to module at app root
try:
    from app.services.reddit_ingest import ingest_once
except Exception:  # pragma: no cover
    try:
        from app import reddit_ingest  # type: ignore
        ingest_once = reddit_ingest.ingest_once  # type: ignore
    except Exception:
        ingest_once = None  # type: ignore

from app.database import SessionLocal  # sync session
from app.db_models import Show, RedditPost

router = APIRouter(prefix="/ingest", tags=["Ingest"])

@router.post("/reddit", summary="Run a one-off Reddit ingest (pulls latest posts, TMDB-match, upsert Shows)")
def ingest_reddit(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    if ingest_once is None:
        raise HTTPException(status_code=500, detail="reddit_ingest.ingest_once not found")
    try:
        result = ingest_once(limit=limit)  # sync function; FastAPI runs sync endpoints in a threadpool
        return {"ok": True, **(result or {})}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reddit/relink", summary="Relink orphan Reddit posts to shows by naive title contains match")
def relink_posts(limit_shows: int = Query(2000, ge=1, le=10000)) -> dict[str, Any]:
    """
    For posts with NULL show_id, try to assign a show_id by matching Show.title substring (case-insensitive).
    Heuristic backfill for posts fetched before a TMDB match existed.
    """
    linked = 0
    with SessionLocal() as db:  # sync session
        shows = db.execute(select(Show).where(Show.title.isnot(None)).limit(limit_shows)).scalars().all()
        idx = [(s.show_id, (s.title or "").lower()) for s in shows if s.title]
        if not idx:
            return {"ok": True, "linked": 0}

        orphans = db.execute(select(RedditPost).where(RedditPost.show_id.is_(None))).scalars().all()
        for p in orphans:
            t = (p.title or "").lower().strip()
            if not t:
                continue
            chosen = next((sid for sid, stitle in idx if stitle and stitle in t), None)
            if chosen:
                p.show_id = chosen
                linked += 1

        if linked:
            db.commit()

    return {"ok": True, "linked": linked}
