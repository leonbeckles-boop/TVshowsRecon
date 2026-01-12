from __future__ import annotations

import os
import traceback
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://tvuser:tvpass@db:5432/tvrecs")
_engine = create_async_engine(DATABASE_URL, future=True)
AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

__all__ = ["mmr_diversify", "hybrid_recommendations_for_user_async"]


def mmr_diversify(candidates: List[Tuple[int, float]], k: int, lambda_: float = 0.3) -> List[Tuple[int, float]]:
    if not candidates:
        return []
    pool = list(sorted(candidates, key=lambda x: x[1], reverse=True))
    selected: List[Tuple[int, float]] = []
    while pool and len(selected) < k:
        if not selected:
            selected.append(pool.pop(0))
            continue
        best_idx = 0
        best_val = float("-inf")
        for i, (cid, score) in enumerate(pool):
            sim = 1.0 / (1.0 + i)  # crude similarity proxy by position
            mmr_val = lambda_ * score - (1 - lambda_) * sim
            if mmr_val > best_val:
                best_val = mmr_val
                best_idx = i
        selected.append(pool.pop(best_idx))
    return selected


async def _db_ping(session: AsyncSession) -> None:
    await session.execute(text("SELECT 1"))


async def _fetch_favorites(session: AsyncSession, user_id: int) -> List[int]:
    q = text("SELECT tmdb_id FROM user_favorites WHERE user_id = :uid")
    rows = (await session.execute(q, {"uid": user_id})).all()
    return [int(r[0]) for r in rows]


async def _fetch_not_interested(session: AsyncSession, user_id: int) -> List[int]:
    if_exists = text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema='public' AND table_name='not_interested'
        )
    """)
    exists = (await session.execute(if_exists)).scalar() or False
    if not exists:
        return []
    q = text("SELECT tmdb_id FROM not_interested WHERE user_id = :uid")
    rows = (await session.execute(q, {"uid": user_id})).all()
    return [int(r[0]) for r in rows]


async def _aggregate_pairs_for_favs(session: AsyncSession, favs: Iterable[int]) -> Dict[int, int]:
    agg: Dict[int, int] = defaultdict(int)
    q_a = text("""
        SELECT tmdb_id_b AS rec_id, pair_count
        FROM reddit_pairs
        WHERE tmdb_id_a = :fav
    """)
    q_b = text("""
        SELECT tmdb_id_a AS rec_id, pair_count
        FROM reddit_pairs
        WHERE tmdb_id_b = :fav
    """)
    for fav in favs:
        for q in (q_a, q_b):
            rows = (await session.execute(q, {"fav": fav})).all()
            for rec_id, cnt in rows:
                if rec_id is None:
                    continue
                agg[int(rec_id)] += int(cnt or 0)
    return agg


async def hybrid_recommendations_for_user_async(
    user_id: int,
    limit: int = 24,
    w_tmdb: float = 0.6,
    w_reddit: float = 0.3,
    w_pair: float = 0.25,
    mmr_lambda: float = 0.3,
    orig_lang: Optional[str] = None,
    debug: Optional[int | bool] = None,
    **kwargs,
) -> dict:
    try:
        async with AsyncSessionLocal() as session:
            await _db_ping(session)
            favorites = await _fetch_favorites(session, user_id)
            if not favorites:
                return {
                    "items": [],
                    "meta": {
                        "reason": "no_favorites",
                        "detail": "User has no favorites; nothing to seed reddit_pairs.",
                        "debug_echo": bool(debug) if debug is not None else None,
                    },
                }
            notint = set(await _fetch_not_interested(session, user_id))
            agg = await _aggregate_pairs_for_favs(session, favorites)

            fav_set = set(favorites)
            filtered = [
                (tmdb_id, score)
                for tmdb_id, score in agg.items()
                if tmdb_id not in fav_set and tmdb_id not in notint
            ]

            filtered.sort(key=lambda x: x[1], reverse=True)
            diversified = mmr_diversify(filtered, k=limit, lambda_=mmr_lambda) if filtered else []
            items = [{"tmdb_id": tmdb_id, "score": float(score)} for tmdb_id, score in diversified[:limit]]

            return {
                "items": items,
                "meta": {
                    "source": "reddit_pairs_only",
                    "favorites_seed_count": len(favorites),
                    "excluded": {"favorites": len(fav_set), "not_interested": len(notint)},
                    "w_tmdb": w_tmdb,
                    "w_reddit": w_reddit,
                    "w_pair": w_pair,
                    "ignored_kwargs": list(kwargs.keys()) if kwargs else [],
                    "debug_echo": bool(debug) if debug is not None else None,
                },
            }
    except Exception as e:
        return {
            "items": [],
            "meta": {
                "reason": "adapter_exception",
                "error": str(e),
                "traceback": traceback.format_exc() if debug else None,
                "ignored_kwargs": list(kwargs.keys()) if kwargs else [],
            },
        }
