from __future__ import annotations

import asyncio
import logging
import os
from math import inf
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import select, text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recs", tags=["recs"])

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

# ========== Optional adapter imports (kept resilient) ==========
try:
    from app.services.recs_hybrid_adapter import (  # type: ignore
        hybrid_recommendations_for_user_async,
        mmr_diversify as _adapter_mmr_diversify,
    )
except Exception as e:  # pragma: no cover
    logger.warning("Hybrid adapter not available: %s", e)
    hybrid_recommendations_for_user_async = None  # type: ignore[assignment]
    _adapter_mmr_diversify = None  # type: ignore[assignment]

# Optional ORM model for favorites if present
try:
    from app.db_models import FavoriteTmdb  # type: ignore
except Exception:
    FavoriteTmdb = None  # type: ignore

# ========== Types ==========
JsonItem = Dict[str, Any]
AnyItem = Union[JsonItem, int, str, Tuple[Any, ...], List[Any]]

# ========== Utilities ==========
def _to_int_or_none(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None

def _to_float_or_zero(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def _coerce_item(it: AnyItem) -> Optional[JsonItem]:
    """
    Coerce into {"tmdb_id": int, "score": float, ...}.
    Accepts dicts, ints / numeric strings, or (id[,score]) tuples.
    """
    if isinstance(it, dict):
        tmdb_id = _to_int_or_none(it.get("tmdb_id"))
        if tmdb_id is None:
            tmdb_id = _to_int_or_none(it.get("id"))
        if tmdb_id is None:
            return None
        score = _to_float_or_zero(it.get("score", 0.0))
        out = dict(it)
        out["tmdb_id"] = tmdb_id
        out["score"] = score
        return out

    if isinstance(it, (int, str)):
        tmdb_id = _to_int_or_none(it)
        if tmdb_id is None:
            return None
        return {"tmdb_id": tmdb_id, "score": 0.0}

    if isinstance(it, (tuple, list)) and len(it) >= 1:
        tmdb_id = _to_int_or_none(it[0])
        if tmdb_id is None:
            return None
        score = _to_float_or_zero(it[1]) if len(it) >= 2 else 0.0
        return {"tmdb_id": tmdb_id, "score": score}

    return None

def _coerce_items(items: List[AnyItem]) -> List[JsonItem]:
    out: List[JsonItem] = []
    for it in items:
        c = _coerce_item(it)
        if c is not None:
            out.append(c)
        else:
            logger.warning("Skipping uncoercible item: %r", it)
    return out

# ========== Local MMR (dict-based) ==========
def _default_sim(a: JsonItem, b: JsonItem) -> float:
    at = set(str(a.get("title", "")).lower().split())
    bt = set(str(b.get("title", "")).lower().split())
    if not at or not bt:
        return 0.0
    return len(at & bt) / max(1, len(at | bt))

def _local_mmr_dict_items(
    items: List[JsonItem],
    lambda_: float = 0.3,
    k: Optional[int] = None,
    sim: Optional[Callable[[JsonItem, JsonItem], float]] = None,
) -> List[JsonItem]:
    if not items:
        return items
    if k is None:
        k = len(items)
    sim = sim or _default_sim

    items = _coerce_items(items)
    scored = [(float(it.get("score", 0.0)), it) for it in items]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected: List[JsonItem] = []
    candidates: List[JsonItem] = [it for _, it in scored]

    while candidates and len(selected) < k:
        best_item: Optional[JsonItem] = None
        best_val = -inf
        for c in candidates:
            rel = float(c.get("score", 0.0))
            div_penalty = max((sim(c, s) for s in selected), default=0.0)
            val = lambda_ * rel - (1.0 - lambda_) * div_penalty
            if val > best_val:
                best_val = val
                best_item = c
        if best_item is None:  # safety
            break
        selected.append(best_item)
        candidates = [x for x in candidates if x is not best_item]

    return selected

def mmr_lambda_sane(x: float) -> float:
    try:
        xf = float(x)
    except Exception:
        return 0.3
    if xf < 0.0:
        return 0.0
    if xf > 1.0:
        return 1.0
    return xf

def mmr_diversify(
    items: List[AnyItem],
    lambda_: float = 0.3,
    k: Optional[int] = None,
    sim: Optional[Callable[[JsonItem, JsonItem], float]] = None,
) -> List[JsonItem]:
    items_dict = _coerce_items(list(items))

    if _adapter_mmr_diversify is not None:
        try:
            tuples: List[Tuple[int, float]] = [
                (int(it["tmdb_id"]), float(it.get("score", 0.0))) for it in items_dict
            ]
            k_eff = len(tuples) if k is None else k
            tuples_out = _adapter_mmr_diversify(tuples, k=k_eff, lambda_=lambda_)
            return [{"tmdb_id": int(t[0]), "score": float(t[1])} for t in tuples_out]
        except Exception as e:  # pragma: no cover
            logger.warning("Adapter mmr_diversify failed; using local fallback: %s", e)

    return _local_mmr_dict_items(items_dict, lambda_=mmr_lambda_sane(lambda_), k=k, sim=sim)

# ========== TMDb enrichment ==========
async def _tmdb_details(tmdb_id: int) -> Dict[str, Any]:
    api_key = os.environ.get("TMDB_API_KEY") or os.environ.get("TMDB_KEY") or os.environ.get("TMDB_API")
    if not api_key:
        return {"tmdb_id": tmdb_id}
    url = f"{TMDB_API}/tv/{tmdb_id}?api_key={api_key}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return {"tmdb_id": tmdb_id}
        data = r.json()
        poster_path = (data.get("poster_path") or "").lstrip("/")
        poster_url = f"{TMDB_IMG}/{poster_path}" if poster_path else None

        # NEW: get genres (names + ids)
        genres_arr = data.get("genres") or []
        genre_names = [str(g.get("name")).strip() for g in genres_arr if g and g.get("name")]
        genre_ids = [int(g.get("id")) for g in genres_arr if g and isinstance(g.get("id"), int)]

        return {
            "tmdb_id": tmdb_id,
            "name": data.get("name") or data.get("original_name"),
            "title": data.get("name") or data.get("original_name"),
            "overview": data.get("overview"),
            "poster_path": data.get("poster_path"),
            "poster_url": poster_url,
            "first_air_date": data.get("first_air_date"),
            "origin_country": data.get("origin_country"),
            "original_language": data.get("original_language"),
            "genres": genre_names,      # <-- names
            "genre_ids": genre_ids,     # <-- ids
        }

async def _enrich_with_tmdb(items: List[JsonItem]) -> List[JsonItem]:
    ids: List[int] = []
    seen: set[int] = set()
    for it in items:
        tid = it.get("tmdb_id")
        if isinstance(tid, int) and tid not in seen:
            seen.add(tid)
            ids.append(tid)

    ids = ids[:40]  # cap
    details: Dict[int, Dict[str, Any]] = {}
    if ids:
        results = await asyncio.gather(*[_tmdb_details(t) for t in ids], return_exceptions=True)
        for d in results:
            if isinstance(d, dict) and d.get("tmdb_id"):
                details[int(d["tmdb_id"])] = d

    enriched: List[JsonItem] = []
    for it in items:
        tid = int(it.get("tmdb_id", -1))
        merged = {**it, **details.get(tid, {})}
        if "title" not in merged and "name" in merged:
            merged["title"] = merged["name"]
        enriched.append(merged)
    return enriched

# ========== Endpoint ==========
@router.get("/{user_id}")
async def get_recommendations(
    user_id: int,
    limit: int = Query(24, ge=1, le=200),
    w_tmdb: float = Query(0.6, ge=0.0, le=1.0),
    w_reddit: float = Query(0.3, ge=0.0, le=1.0),
    w_pair: float = Query(0.25, ge=0.0, le=1.0),
    mmr_lambda: float = Query(0.3, ge=0.0, le=1.0),
    orig_lang: Optional[str] = Query(None, description="Optional ISO-639-1 language filter, e.g. 'en'"),
    genres: Optional[List[str]] = Query(None, description="Optional genre name filters; OR-match"),  # <-- NEW
    debug: int = Query(0, ge=0, le=1),
    flat: int = Query(1, ge=0, le=1, description="If 1: plain list (frontend default). If 0: include meta."),
) -> Any:
    """Hybrid recommendations for a user, with MMR diversification and TMDb enrichment."""
    if hybrid_recommendations_for_user_async is None:
        items: List[JsonItem] = []
        return items if flat else {"items": items, "meta": {"reason": "adapter_unavailable"}}

    try:
        resp: Dict[str, Any] = await hybrid_recommendations_for_user_async(
            user_id=user_id,
            limit=limit,
            w_tmdb=w_tmdb,
            w_reddit=w_reddit,
            w_pair=w_pair,
            orig_lang=orig_lang,
            debug=bool(debug),
        )
        raw_items = resp.get("items", [])
        items: List[JsonItem] = _coerce_items(list(raw_items))
    except Exception as e:
        logger.exception("hybrid_recommendations_for_user_async failed")
        items = []
        return items if flat else {"items": items, "meta": {"reason": "adapter_error", "detail": str(e)}}

    # MMR diversify
    items = mmr_diversify(items, lambda_=mmr_lambda_sane(mmr_lambda), k=limit)

    # Exclude user's favorites
    try:
        if FavoriteTmdb is not None:
            from app.database import get_async_db  # type: ignore
            async for db in get_async_db():
                res = await db.execute(
                    select(FavoriteTmdb.tmdb_id).where(FavoriteTmdb.user_id == user_id)  # type: ignore
                )
                fav_ids = {int(row[0]) for row in res.fetchall()}
                items = [x for x in items if int(x.get("tmdb_id", -1)) not in fav_ids]
                break
        else:
            from app.database import get_async_db  # type: ignore
            async for db in get_async_db():
                res = await db.execute(
                    text("SELECT tmdb_id FROM user_favorites WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                fav_ids = {int(row[0]) for row in res.fetchall()}
                items = [x for x in items if int(x.get("tmdb_id", -1)) not in fav_ids]
                break
    except Exception as e:  # pragma: no cover
        logger.warning("Favorite filter skipped: %s", e)

    # Exclude user's "not interested" list
    try:
        from app.database import get_async_db  # type: ignore
        async for db in get_async_db():
            res = await db.execute(
                text("SELECT tmdb_id FROM not_interested WHERE user_id = :uid"),
                {"uid": user_id},
            )
            blocked_ids = {int(row[0]) for row in res.fetchall()}
            if blocked_ids:
                items = [x for x in items if int(x.get("tmdb_id", -1)) not in blocked_ids]
            break
    except Exception as e:  # pragma: no cover
        logger.warning("Not-interested filter skipped: %s", e)

    # Enrich (adds genres/genre_ids)
    try:
        items = await _enrich_with_tmdb(items)
    except Exception as e:  # pragma: no cover
        logger.warning("TMDb enrichment failed: %s", e)

    # Local language filter (fallback)
    if orig_lang:
        try:
            ol = str(orig_lang).lower()
            items = [x for x in items if str(x.get("original_language", "")).lower() == ol]
        except Exception:
            pass

    # NEW: Local genre filter (OR-match by genre names)
    if genres:
        try:
            want = {str(g).strip().lower() for g in genres if g}
            if want:
                filtered: List[JsonItem] = []
                for it in items:
                    names = it.get("genres") or []
                    if isinstance(names, list):
                        names_l = {str(n).strip().lower() for n in names if n}
                    else:
                        names_l = set()
                    if names_l & want:
                        filtered.append(it)
                items = filtered
        except Exception as e:
            logger.warning("Genre filter skipped: %s", e)

    items = items[:limit]

    if flat:
        return items

    return {
        "items": items,
        "meta": {
            "count": len(items),
            "w_tmdb": w_tmdb,
            "w_reddit": w_reddit,
            "w_pair": w_pair,
            "mmr_lambda": mmr_lambda_sane(mmr_lambda),
            "applied_orig_lang": orig_lang or None,
            "applied_genres": genres or None,   # <-- NEW
            "filtered_favorites": True,
            "filtered_not_interested": True,
        },
    }
