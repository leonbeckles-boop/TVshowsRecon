from __future__ import annotations

from typing import Any, Dict, List, Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_db

# Auth dependency import (kept defensive so router still mounts if paths move)
try:
    from app.auth.dependencies import require_user  # type: ignore
except Exception:  # pragma: no cover
    try:
        from app.security import require_user  # type: ignore
    except Exception:  # pragma: no cover
        async def require_user() -> None:  # type: ignore
            return None


router = APIRouter(prefix="/recs/v3", tags=["recs_v3"])


def _poster_url_from_path(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    p = p.strip()
    if not p:
        return None
    if p.startswith("http://") or p.startswith("https://"):
        return p
    # TMDb poster paths often start with "/"
    if p.startswith("/"):
        return f"https://image.tmdb.org/t/p/w500{p}"
    # If it's some other relative-ish string, treat it as path
    return f"https://image.tmdb.org/t/p/w500/{p}"


async def _get_fav_ids(db: AsyncSession, user_id: int) -> List[int]:
    rows = (
        await db.execute(
            text(
                """
                SELECT tmdb_id
                FROM user_favorites
                WHERE user_id = :uid
                """
            ),
            {"uid": user_id},
        )
    ).scalars().all()
    return [int(x) for x in rows]


async def _get_not_interested_ids(db: AsyncSession, user_id: int) -> List[int]:
    rows = (
        await db.execute(
            text(
                """
                SELECT tmdb_id
                FROM not_interested
                WHERE user_id = :uid
                """
            ),
            {"uid": user_id},
        )
    ).scalars().all()
    return [int(x) for x in rows]


async def _fetch_show_lite(db: AsyncSession, tmdb_id: int) -> Optional[Dict[str, Any]]:
    q = text(
        """
        SELECT
          show_id,
          title,
          COALESCE(NULLIF(poster_path, ''), NULLIF(poster_url, '')) AS poster_url,
          year
        FROM shows
        WHERE show_id = :sid
        """
    )
    try:
        row = (await db.execute(q, {"sid": tmdb_id})).mappings().first()
        if not row:
            return None
        poster_url = _poster_url_from_path(row.get("poster_url"))
        return {
            "tmdb_id": int(row["show_id"]),
            "title": row.get("title"),
            "poster_url": poster_url,
            "year": row.get("year"),
        }
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        raise


async def _fetch_many_show_lite(db: AsyncSession, tmdb_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not tmdb_ids:
        return {}
    q = (
        text(
            """
            SELECT
              show_id,
              title,
              COALESCE(NULLIF(poster_path, ''), NULLIF(poster_url, '')) AS poster_url,
              year
            FROM shows
            WHERE show_id IN :ids
            """
        )
        .bindparams(bindparam("ids", expanding=True))
    )
    try:
        rows = (await db.execute(q, {"ids": tmdb_ids})).mappings().all()
        out: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            sid = int(r["show_id"])
            out[sid] = {
                "tmdb_id": sid,
                "title": r.get("title"),
                "poster_url": _poster_url_from_path(r.get("poster_url")),
                "year": r.get("year"),
            }
        return out
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        raise


async def _fallback_popular_from_reddit_scores(db: AsyncSession, limit: int) -> List[Dict[str, Any]]:
    # reddit_scores: tmdb_id (PK), score_reddit (numeric)
    rows = (
        await db.execute(
            text(
                """
                SELECT tmdb_id, score_reddit
                FROM reddit_scores
                ORDER BY score_reddit DESC NULLS LAST
                LIMIT :lim
                """
            ),
            {"lim": limit},
        )
    ).mappings().all()

    ids = [int(r["tmdb_id"]) for r in rows]
    meta = await _fetch_many_show_lite(db, ids)

    out: List[Dict[str, Any]] = []
    for r in rows:
        tid = int(r["tmdb_id"])
        m = meta.get(tid) or {"tmdb_id": tid, "title": None, "poster_url": None}
        out.append(
            {
                "tmdb_id": tid,
                "title": m.get("title"),
                "poster_url": m.get("poster_url"),
                "score": float(r["score_reddit"] or 0.0),
            }
        )
    return out


async def _compute_recs_from_pairs(
    db: AsyncSession,
    fav_ids: List[int],
    exclude_ids: List[int],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Use reddit_pairs (tmdb_id_a, tmdb_id_b, pair_weight) to score candidates.
    """
    if not fav_ids:
        return await _fallback_popular_from_reddit_scores(db, limit)

    sql = (
        text(
            """
            SELECT tmdb_id_b AS tmdb_id, pair_weight
            FROM reddit_pairs
            WHERE tmdb_id_a IN :ids
            UNION ALL
            SELECT tmdb_id_a AS tmdb_id, pair_weight
            FROM reddit_pairs
            WHERE tmdb_id_b IN :ids
            """
        )
        .bindparams(bindparam("ids", expanding=True))
    )

    try:
        rows = (await db.execute(sql, {"ids": fav_ids})).mappings().all()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        raise

    scores: Dict[int, float] = defaultdict(float)
    for r in rows:
        tid = int(r["tmdb_id"])
        if tid in exclude_ids:
            continue
        w = r.get("pair_weight")
        try:
            scores[tid] += float(w or 0.0)
        except Exception:
            continue

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[: max(limit, 1)]
    ids = [tid for tid, _ in ranked]
    meta = await _fetch_many_show_lite(db, ids)

    out: List[Dict[str, Any]] = []
    for tid, sc in ranked:
        m = meta.get(tid) or {"tmdb_id": tid, "title": None, "poster_url": None}
        out.append(
            {
                "tmdb_id": tid,
                "title": m.get("title"),
                "poster_url": m.get("poster_url"),
                "score": float(sc),
            }
        )
    return out


@router.get("/diag-ez")
async def diag_ez() -> Dict[str, Any]:
    return {"ok": True, "router": "recs_v3"}


@router.get("")
async def get_recs_v3_query(
    user_id: int = Query(..., ge=1),
    limit: int = Query(60, ge=1, le=200),
    flat: int = Query(1, ge=0, le=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    # flat is kept for backwards compatibility with the frontend; response is already flat.
    fav_ids = await _get_fav_ids(db, user_id)
    ni_ids = await _get_not_interested_ids(db, user_id)
    exclude = list(set(fav_ids + ni_ids))
    try:
        return await _compute_recs_from_pairs(db, fav_ids, exclude, limit)
    except HTTPException:
        raise
    except Exception as e:
        # Make sure transaction doesn't get stuck
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Internal error in recs_v3") from e


@router.get("/{user_id}")
async def get_recs_v3(
    user_id: int = Path(..., ge=1),
    limit: int = Query(60, ge=1, le=200),
    flat: int = Query(1, ge=0, le=1),
    _: Any = Depends(require_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[Dict[str, Any]]:
    # Path-param version for /api/docs & direct calls
    return await get_recs_v3_query(user_id=user_id, limit=limit, flat=flat, _=_, db=db)
