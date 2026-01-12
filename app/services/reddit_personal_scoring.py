# app/services/reddit_personal_scoring.py
# Updated 2025-10-12
from __future__ import annotations
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import RedditPost, FavoriteTmdb, UserRating
from app.services.reddit_weights import SUB_WEIGHTS, time_decay, base_post_score

try:
    from app.services import title_to_tmdb
except Exception:
    title_to_tmdb = None  # type: ignore

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)

def _age_days(dt: Optional[datetime]) -> float:
    if not dt:
        return 365.0
    return max(0.0, (_now() - dt).total_seconds() / 86400.0)

def _map_title_to_tmdb(title: str) -> Optional[int]:
    if not title:
        return None
    if title_to_tmdb and hasattr(title_to_tmdb, "lookup_tmdb_id_for_title"):
        try:
            tid = title_to_tmdb.lookup_tmdb_id_for_title(title)
            if isinstance(tid, (int, str)) and str(tid).isdigit():
                return int(tid)
        except Exception:
            pass
    return None

def reddit_scores_recent(db: Session, days: int = 45) -> Dict[int, float]:
    since = _now() - timedelta(days=days)
    posts = db.execute(
        select(RedditPost).where(RedditPost.created_utc >= since)
    ).scalars().all()

    scores: Dict[int, float] = {}
    for rp in posts:
        title = (getattr(rp, "title", None) or "").strip()
        sub = (getattr(rp, "subreddit", None) or "").lower().strip()
        created = getattr(rp, "created_utc", None)
        base = base_post_score(getattr(rp, "score", None), getattr(rp, "num_comments", None))
        w_sub = SUB_WEIGHTS.get(sub, 0.3)
        decay = time_decay(_age_days(created))
        raw = base * w_sub * decay

        tmdb_id = getattr(rp, "tmdb_id", None) or _map_title_to_tmdb(title)
        if tmdb_id is None:
            continue
        tid = int(tmdb_id)
        scores[tid] = scores.get(tid, 0.0) + float(raw)
    return scores

def reddit_scores_for_user(db: Session, user_id: int, days: int = 45) -> Dict[int, float]:
    base = reddit_scores_recent(db, days=days)
    if not base:
        return base
    favs = db.execute(select(FavoriteTmdb.tmdb_id).where(FavoriteTmdb.user_id == user_id)).scalars().all()
    ratings = db.execute(select(UserRating.tmdb_id, UserRating.rating).where(UserRating.user_id == user_id)).all()
    seeds = {int(x) for x in favs if x} | {int(tm) for tm, r in ratings if tm and r and float(r) >= 7.0}
    if not seeds:
        return base
    out = dict(base)
    for tid in list(base.keys()):
        if tid in seeds:
            out[tid] = out[tid] * 1.15  # small personalization nudge
    return out
