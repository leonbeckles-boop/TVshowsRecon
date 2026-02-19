from __future__ import annotations
import asyncio
import logging
import math
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.security import require_user_match
from collections.abc import Set
from cachetools import TTLCache
TMDB_API = os.environ.get("TMDB_API", "https://api.themoviedb.org/3")
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
router = APIRouter(prefix="/recs/v3", tags=["recs_v3"])
log = logging.getLogger("recs_v3")
# Require at least this many favourites before we serve any recs
MIN_FAVORITES = 3
# ---------------------------------------------------------------------------
# Improvement #2: Reusable httpx client (created at module level)
# ---------------------------------------------------------------------------
_http_client: httpx.AsyncClient | None = None
def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10)
    return _http_client
# ---------------------------------------------------------------------------
# Improvement #3: In-memory TTL cache for TMDB details
# ---------------------------------------------------------------------------
_tmdb_details_cache: TTLCache = TTLCache(maxsize=2048, ttl=3600)  # 1 hour TTL
# ---------------------------------------------------------------------------
# TMDB helpers
# ---------------------------------------------------------------------------
def _tmdb_api_key() -> str | None:
    """
    Resolve TMDB API key from env.
    IMPORTANT: TMDB_API is the base URL, not the key.
    """
    return os.environ.get("TMDB_API_KEY") or os.environ.get("TMDB_KEY")
async def _tmdb_details(tmdb_id: int) -> Dict[str, Any]:
    """
    Fetch TV details for a tmdb_id from TMDB.
    Returns a dict with the same shape v1/v2 use.
    Improvement #3: Results are cached in-memory with a 1-hour TTL.
    """
    # Check cache first
    if tmdb_id in _tmdb_details_cache:
        return dict(_tmdb_details_cache[tmdb_id])
    api_key = _tmdb_api_key()
    if not api_key:
        return {"tmdb_id": tmdb_id}
    url = f"{TMDB_API}/tv/{tmdb_id}?api_key={api_key}"
    try:
        client = _get_http_client()
        r = await client.get(url)
    except Exception:
        return {"tmdb_id": tmdb_id}
    if r.status_code != 200:
        return {"tmdb_id": tmdb_id}
    data = r.json() or {}
    poster_path = (data.get("poster_path") or "").lstrip("/")
    poster_url = f"{TMDB_IMG}/{poster_path}" if poster_path else None
    genres_arr = data.get("genres") or []
    genre_names = [str(g.get("name")).strip() for g in genres_arr if g and g.get("name")]
    genre_ids: list[int] = []
    for g in genres_arr:
        if not g:
            continue
        gid = g.get("id")
        if isinstance(gid, int):
            genre_ids.append(gid)
    result = {
        "tmdb_id": tmdb_id,
        "name": data.get("name") or data.get("original_name"),
        "title": data.get("name") or data.get("original_name"),
        "overview": data.get("overview"),
        "poster_path": data.get("poster_path"),
        "poster_url": poster_url,
        "first_air_date": data.get("first_air_date"),
        "origin_country": data.get("origin_country"),
        "original_language": data.get("original_language"),
        "genres": genre_names,
        "genre_ids": genre_ids,
        "vote_average": data.get("vote_average"),
        "vote_count": data.get("vote_count"),
        "popularity": data.get("popularity"),
    }
    # Store in cache
    _tmdb_details_cache[tmdb_id] = result
    return dict(result)
async def _tmdb_search_tv(query: str) -> Optional[Dict[str, Any]]:
    """Search TMDB for a TV show by name and return the first result dict (raw)."""
    api_key = _tmdb_api_key()
    if not api_key:
        return None
    q = (query or "").strip()
    if not q:
        return None
    params = {"api_key": api_key, "query": q}
    url = f"{TMDB_API}/search/tv"
    try:
        client = _get_http_client()
        r = await client.get(url, params=params)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    data = r.json() or {}
    results = data.get("results") or []
    if not results:
        return None
    return results[0]
def _recent_first_bucket(items: List[Dict[str, Any]], years: int = 3) -> List[Dict[str, Any]]:
    """Bucket recent releases first; preserve order within each bucket."""
    try:
        now = datetime.now(timezone.utc).date()
        cutoff = now.replace(year=now.year - int(years))
    except Exception:
        cutoff = None
    recent: List[Dict[str, Any]] = []
    older: List[Dict[str, Any]] = []
    for it in items:
        d = it.get("first_air_date")
        dt = None
        if isinstance(d, str) and len(d) >= 10:
            try:
                dt = datetime.strptime(d[:10], "%Y-%m-%d").date()
            except Exception:
                dt = None
        if cutoff and dt and dt >= cutoff:
            recent.append(it)
        else:
            older.append(it)
    return recent + older
async def _tmdb_recommendations_for_fav(tmdb_id: int, api_key: str, max_n: int = 20) -> List[int]:
    """
    Fetch TMDB recommendations for a single favourite show.
    Returns a list of recommended tmdb_ids (TV).
    """
    url = f"{TMDB_API}/tv/{tmdb_id}/recommendations?api_key={api_key}"
    try:
        client = _get_http_client()
        r = await client.get(url)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    data = r.json() or {}
    results = data.get("results") or []
    out: List[int] = []
    for row in results[:max_n]:
        tid = row.get("id")
        if isinstance(tid, int):
            out.append(tid)
    return out
async def _fetch_tmdb_candidates(fav_ids: List[int], block_ids: set[int], limit: int) -> List[Dict[str, Any]]:
    """
    Build TMDB-based candidate list from favourites using /tv/{id}/recommendations.
    Returns [{ tmdb_id, score_raw, source="tmdb_recs" }, ...].
    """
    api_key = _tmdb_api_key()
    if not api_key or not fav_ids:
        return []
    fav_slice = fav_ids[: min(len(fav_ids), 10)]
    tasks = [_tmdb_recommendations_for_fav(fid, api_key, max_n=20) for fid in fav_slice]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    tmdb_ids: set[int] = set()
    for res in results:
        if isinstance(res, Exception):
            continue
        for tid in res:
            if not isinstance(tid, int):
                continue
            if tid in block_ids:
                continue
            tmdb_ids.add(tid)
    items: List[Dict[str, Any]] = []
    for tid in list(tmdb_ids)[: max(limit * 3, limit)]:
        items.append({"tmdb_id": tid, "score_raw": 1.0, "source": "tmdb_recs"})
    return items
async def _fetch_tmdb_trending_candidates(
    allowed_langs: set[str],
    fav_genres: set[int],
    block_ids: set[int],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Build candidate list from TMDB /trending/tv/week, filtered by
    user's languages + favourite genres.
    """
    api_key = _tmdb_api_key()
    if not api_key:
        return []
    url = f"{TMDB_API}/trending/tv/week?api_key={api_key}"
    try:
        client = _get_http_client()
        r = await client.get(url)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    data = r.json() or {}
    results = data.get("results") or []
    items: List[Dict[str, Any]] = []
    max_items = max(limit * 3, limit)
    for row in results:
        tid = row.get("id")
        if not isinstance(tid, int):
            continue
        if tid in block_ids:
            continue
        lang = row.get("original_language")
        if allowed_langs and lang not in allowed_langs:
            continue
        genre_ids = row.get("genre_ids") or []
        gid_set = set(int(g) for g in genre_ids if isinstance(g, int))
        if 10767 in gid_set or 10766 in gid_set:
            continue
        if fav_genres and not (fav_genres & gid_set):
            continue
        pop = row.get("popularity") or 0.0
        try:
            pop = float(pop)
        except Exception:
            pop = 0.0
        base = math.log10(1.0 + max(pop, 0.0))
        score_raw = 0.3 + 0.4 * base
        items.append({"tmdb_id": tid, "score_raw": score_raw, "source": "tmdb_trending"})
        if len(items) >= max_items:
            break
    return items
# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
async def _get_block_ids(session: AsyncSession, user_id: int) -> set[int]:
    """
    IDs we must NOT recommend:
      - user_favorites.tmdb_id
      - not_interested.tmdb_id
      - user_watchlist.tmdb_id
    """
    sql = text(
        """
        SELECT tmdb_id
        FROM user_favorites
        WHERE user_id = :uid
        UNION
        SELECT tmdb_id
        FROM not_interested
        WHERE user_id = :uid
        UNION
        SELECT tmdb_id
        FROM user_watchlist
        WHERE user_id = :uid
        """
    )
    res = await session.execute(sql, {"uid": user_id})
    rows = res.mappings().all()
    return {int(r["tmdb_id"]) for r in rows if r.get("tmdb_id") is not None}
async def _fetch_user_favorites(session: AsyncSession, user_id: int) -> List[int]:
    sql = text(
        """
        SELECT tmdb_id
        FROM user_favorites
        WHERE user_id = :uid
        ORDER BY id ASC
        """
    )
    res = await session.execute(sql, {"uid": user_id})
    rows = res.mappings().all()
    favs: List[int] = []
    for r in rows:
        try:
            favs.append(int(r["tmdb_id"]))
        except Exception:
            continue
    return favs
async def _fetch_reddit_candidates_from_pairs(
    session: AsyncSession,
    fav_ids: List[int],
    limit: int,
    block_ids: set[int],
) -> List[Dict[str, Any]]:
    """
    Build reddit candidates using the existing global reddit_pairs table.
    Improvement #4: Apply IDF-style weighting so niche co-occurrences
    score higher than popular show mentions.
    """
    if not fav_ids:
        return []
    raw_limit = max(limit * 6, limit * 3, limit)
    # First, get the total number of distinct shows in reddit_pairs for IDF
    try:
        count_sql = text("SELECT COUNT(DISTINCT tmdb_id_a) + COUNT(DISTINCT tmdb_id_b) AS total FROM reddit_pairs")
        count_res = await session.execute(count_sql)
        total_shows = int((count_res.scalar() or 1000))
    except Exception:
        total_shows = 1000
    sql = text(
        """
        SELECT
            CASE
                WHEN rp.tmdb_id_a IN :favs THEN rp.tmdb_id_b
                ELSE rp.tmdb_id_a
            END AS tmdb_id,
            SUM(rp.pair_weight) AS weight,
            COUNT(*) AS mention_count
        FROM reddit_pairs rp
        WHERE (rp.tmdb_id_a IN :favs OR rp.tmdb_id_b IN :favs)
        GROUP BY 1
        ORDER BY weight DESC NULLS LAST
        LIMIT :limit
        """
    ).bindparams(
        bindparam("favs", expanding=True),
        bindparam("limit"),
    )
    try:
        res = await session.execute(sql, {"favs": fav_ids, "limit": raw_limit})
    except Exception:
        try:
            print("reddit_pairs query failed; skipping reddit candidates", flush=True)
        except Exception:
            pass
        log.exception("reddit_pairs query failed; skipping reddit candidates")
        return []
    rows = res.mappings().all()
    items: List[Dict[str, Any]] = []
    # Improvement #4: IDF-weighted scoring
    # Also gather a frequency SQL for how often each candidate appears across all pairs
    # We approximate IDF using mention_count from the query above
    for r in rows:
        tid = r.get("tmdb_id")
        if tid is None:
            continue
        try:
            tid_i = int(tid)
        except Exception:
            continue
        if tid_i in block_ids:
            continue
        w = r.get("weight") or 0.0
        mention_count = r.get("mention_count") or 1
        try:
            w_f = float(w)
            mc = int(mention_count)
        except Exception:
            w_f = 0.0
            mc = 1
        if w_f <= 0:
            continue
        # IDF: niche shows (fewer mentions) get boosted
        idf = math.log10(total_shows / (1.0 + mc))
        score_raw = w_f * max(idf, 0.1)  # floor IDF so popular shows aren't zeroed
        items.append({"tmdb_id": tid_i, "score_raw": score_raw, "source": "reddit_pairs"})
        if len(items) >= raw_limit:
            break
    return items
# ---------------------------------------------------------------------------
# Scoring & MMR
# ---------------------------------------------------------------------------
def _normalise(vals: List[float]) -> List[float]:
    if not vals:
        return []
    vmax = max(vals)
    if vmax <= 0:
        return [0.0 for _ in vals]
    return [v / vmax for v in vals]
def _tmdb_quality(item: Dict[str, Any]) -> float:
    """TMDB quality heuristic: confidence-adjusted rating + log-squashed popularity."""
    va = item.get("vote_average") or 0.0
    vc = item.get("vote_count") or 0
    pop = item.get("popularity") or 0.0
    try:
        va = float(va)
    except Exception:
        va = 0.0
    try:
        vc = float(vc)
    except Exception:
        vc = 0.0
    try:
        pop = float(pop)
    except Exception:
        pop = 0.0
    C = 6.5
    m = 50.0
    v = max(vc, 0.0)
    R = max(va, 0.0)
    if v <= 0:
        rating_conf = 0.0
    else:
        rating_conf = (v / (v + m)) * R + (m / (v + m)) * C
    pop_term = math.log10(1.0 + max(pop, 0.0))
    return float(rating_conf + 0.5 * pop_term)
def _passes_quality_filter(
    it: Dict[str, Any],
    *,
    min_vote_average: float = 6.0,
    min_vote_count: int = 25,
    allow_if_vote_average_ge: float = 7.5,
    block_zero_votes: bool = True,
    min_popularity: float = 0.0,
    block_zero_popularity: bool = False,
    include_null_first_air_dates: bool = True,
    allow_future_first_air_dates: bool = True,
) -> bool:
    fad = it.get("first_air_date") or it.get("first_air_date_str") or it.get("first_air")
    if not fad:
        if not include_null_first_air_dates:
            return False
    else:
        if not allow_future_first_air_dates and isinstance(fad, str) and len(fad) >= 10:
            try:
                from datetime import date
                y, m, d = int(fad[0:4]), int(fad[5:7]), int(fad[8:10])
                if date(y, m, d) > date.today():
                    return False
            except Exception:
                pass
    try:
        pop = float(it.get("popularity") or 0.0)
    except Exception:
        pop = 0.0
    if block_zero_popularity and pop <= 0.0:
        return False
    if pop < float(min_popularity):
        return False
    try:
        vc = int(it.get("vote_count") or 0)
    except Exception:
        vc = 0
    try:
        va = float(it.get("vote_average") or 0.0)
    except Exception:
        va = 0.0
    if block_zero_votes and (vc <= 0 or va <= 0.0):
        return False
    if va >= allow_if_vote_average_ge:
        return True
    if vc < int(min_vote_count) and va < float(min_vote_average):
        return False
    return True
def _candidate_ok(
    it: Dict[str, Any],
    *,
    allowed_langs: Optional[Set[str]] = None,
    block_ids: Optional[Set[int]] = None,
    include_null_first_air_dates: bool = True,
    quality_cfg: Optional[Dict[str, Any]] = None,
) -> bool:
    try:
        tmdb_id = int(it.get("tmdb_id") or it.get("id") or 0)
    except Exception:
        tmdb_id = 0
    if tmdb_id and block_ids and tmdb_id in block_ids:
        return False
    lang = (it.get("original_language") or it.get("originalLanguage") or "").strip()
    if allowed_langs and lang and lang not in allowed_langs:
        return False
    cfg = dict(quality_cfg or {})
    cfg.setdefault("include_null_first_air_dates", include_null_first_air_dates)
    return _passes_quality_filter(it, **cfg)
def _quality_cfg_from_request() -> Dict[str, Any]:
    def _get_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except Exception:
            return default
    def _get_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)))
        except Exception:
            return default
    return {
        "min_vote_average": _get_float("QUALITY_MIN_VOTE_AVERAGE", 6.0),
        "min_vote_count": _get_int("QUALITY_MIN_VOTE_COUNT", 25),
        "allow_if_vote_average_ge": _get_float("QUALITY_ALLOW_HIGH_AVG", 7.5),
        "block_zero_votes": os.getenv("QUALITY_BLOCK_ZERO", "1") == "1",
        "min_popularity": _get_float("QUALITY_MIN_POPULARITY", 0.0),
        "block_zero_popularity": os.getenv("QUALITY_BLOCK_ZERO_POP", "0") == "1",
        "include_null_first_air_dates": os.getenv("QUALITY_INCLUDE_NULL_FIRST_AIR", "1") == "1",
        "allow_future_first_air_dates": os.getenv("QUALITY_ALLOW_FUTURE_FIRST_AIR", "1") == "1",
    }
def _similarity(a: Dict[str, Any], b: Dict[str, Any], fav_genre_counts: Optional[Dict[int, int]] = None) -> float:
    """
    Similarity used for both MMR and favourite-similarity.
    Improvement #7: Weighted Jaccard — genre frequency in favourites acts as weight,
    so a user's dominant genres contribute more to similarity.
    Falls back to standard Jaccard when fav_genre_counts is not provided.
    """
    ga = set(a.get("genre_ids") or [])
    gb = set(b.get("genre_ids") or [])
    if not ga or not gb:
        base = 0.0
    elif fav_genre_counts:
        # Weighted Jaccard: weight each genre by its frequency in favourites
        all_genres = ga | gb
        intersection_weight = 0.0
        union_weight = 0.0
        for g in all_genres:
            w = fav_genre_counts.get(g, 1)  # default weight 1 for unknown genres
            in_a = g in ga
            in_b = g in gb
            if in_a and in_b:
                intersection_weight += w
            union_weight += w
        base = intersection_weight / union_weight if union_weight > 0 else 0.0
        inter = len(ga & gb)
        if inter == 1:
            base *= 0.6
        elif inter >= 3:
            base *= 1.1
    else:
        inter = len(ga & gb)
        union = len(ga | gb) or 1
        base = inter / union
        if inter == 1:
            base *= 0.6
        elif inter >= 3:
            base *= 1.1
    la = a.get("original_language")
    lb = b.get("original_language")
    if la and lb and la == lb:
        base += 0.1
    return float(max(0.0, min(base, 1.0)))
def _mmr_diversify(items: List[Dict[str, Any]], k: int, mmr_lambda: float) -> List[Dict[str, Any]]:
    if not items or k <= 0:
        return []
    remaining = list(items)
    selected: List[Dict[str, Any]] = []
    while remaining and len(selected) < k:
        best_item = None
        best_score = None
        for cand in remaining:
            rel = float(cand.get("score", 0.0))
            if not selected:
                div_penalty = 0.0
            else:
                div_penalty = max(_similarity(cand, s) for s in selected)
            mmr_score = mmr_lambda * rel - (1.0 - mmr_lambda) * div_penalty
            if best_score is None or mmr_score > best_score:
                best_score = mmr_score
                best_item = cand
        if best_item is None:
            break
        selected.append(best_item)
        remaining = [c for c in remaining if c["tmdb_id"] != best_item["tmdb_id"]]
    return selected
# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/diag-ez")
async def diag_ez() -> Dict[str, Any]:
    return {"ok": True, "who": "recs_v3"}
@router.get("/diag/quality-filter")
async def diag_quality_filter(
    tmdb_id: int = Query(..., ge=1),
    min_vote_average: float | None = Query(None, ge=0.0, le=10.0),
    min_vote_count: int | None = Query(None, ge=0),
    allow_if_vote_average_ge: float | None = Query(None, ge=0.0, le=10.0),
    block_zero_votes: bool | None = Query(None),
) -> Dict[str, Any]:
    cfg = _quality_cfg_from_request()
    if min_vote_average is not None:
        cfg["min_vote_average"] = float(min_vote_average)
    if min_vote_count is not None:
        cfg["min_vote_count"] = int(min_vote_count)
    if allow_if_vote_average_ge is not None:
        cfg["allow_if_vote_average_ge"] = float(allow_if_vote_average_ge)
    if block_zero_votes is not None:
        cfg["block_zero_votes"] = bool(block_zero_votes)
    details = await _tmdb_details(tmdb_id)
    passed = _passes_quality_filter(details, **cfg)
    return {"tmdb_id": tmdb_id, "passed": passed, "cfg": cfg, "details": details}
@router.get("/{user_id}")
async def get_recs_v3(
    user_id: int,
    limit: int = Query(36, ge=1, le=200),
    w_tmdb: float = Query(0.5, ge=0.0, le=1.0),
    w_reddit: float = Query(0.5, ge=0.0, le=1.0),
    w_personal: float = Query(0.3, ge=0.0, le=1.0),
    # Improvement #6: Raised default MMR lambda from 0.3 to 0.65 (relevance-first)
    mmr_lambda: float = Query(0.65, ge=0.0, le=1.0),
    flat: int = Query(0),
    recent_first: int = Query(0, description="If 1, show newest releases first (while keeping relevance within buckets)."),
    recent_years: int = Query(3, ge=1, le=20, description="Definition of recent for recent_first."),
    freshness_boost: int = Query(0, description="If 1, apply a recency boost to ranking (newer releases score higher)."),
    fav_anchor_boost: float = Query(0.08, ge=0.0, le=0.3, description="Boost factor applied by fav_similarity (0 disables)."),
    _: Any = Depends(require_user_match),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """
    v3 recommendations — improved version with:
      - IDF-weighted reddit pairs (#4)
      - Weighted Jaccard genre similarity (#7)
      - Exponential temporal decay (#8)
      - Multi-signal score merging (#9)
      - Relevance-first MMR default (#6)
      - Cached TMDB details (#3)
      - Reusable HTTP client (#2)
    """
    block_ids: set[int] = set()
    fav_ids: List[int] = []
    now_year = datetime.now(timezone.utc).year
    try:
        block_ids = await _get_block_ids(session, user_id)
        fav_ids = await _fetch_user_favorites(session, user_id)
        if len(fav_ids) < MIN_FAVORITES:
            if flat:
                return []
            return {
                "items": [],
                "meta": {
                    "user_id": user_id,
                    "n_candidates": 0,
                    "n_favorites": len(fav_ids),
                    "min_favorites": MIN_FAVORITES,
                    "reason": "not_enough_favorites",
                    "w_tmdb": w_tmdb,
                    "w_reddit": w_reddit,
                    "w_personal": w_personal,
                    "mmr_lambda": mmr_lambda,
                },
            }
        # Reddit candidates (with IDF weighting — Improvement #4)
        reddit_base: List[Dict[str, Any]] = []
        if w_reddit > 0:
            reddit_base = await _fetch_reddit_candidates_from_pairs(session, fav_ids, limit, block_ids)
        # Favourite details for language/genre profile
        fav_details: List[Dict[str, Any]] = await asyncio.gather(*[_tmdb_details(fid) for fid in fav_ids])
        # Language profile
        allowed_langs = {d.get("original_language") for d in fav_details if d.get("original_language")}
        # Genre profile (counts for taste vector)
        fav_genre_counts: Dict[int, int] = {}
        for d in fav_details:
            for gid in d.get("genre_ids") or []:
                try:
                    g = int(gid)
                except Exception:
                    continue
                fav_genre_counts[g] = fav_genre_counts.get(g, 0) + 1
        fav_genres_all = set(fav_genre_counts.keys())
        # Hard exclusions for Documentary/Reality
        excluded_genres: set[int] = set()
        total_favs = max(1, len(fav_details))
        rep_threshold = max(2, int(math.ceil(0.15 * total_favs)))
        doc_count = fav_genre_counts.get(99, 0)
        reality_count = fav_genre_counts.get(10764, 0)
        if doc_count < rep_threshold:
            excluded_genres.add(99)
        if reality_count < rep_threshold:
            excluded_genres.add(10764)
        fav_genre_norm = math.sqrt(sum(c * c for c in fav_genre_counts.values())) or 1.0
        # TMDB recs from favourites
        tmdb_base: List[Dict[str, Any]] = []
        if w_tmdb > 0:
            tmdb_base = await _fetch_tmdb_candidates(fav_ids, block_ids, limit)
        # TMDB trending, filtered by taste
        trending_base: List[Dict[str, Any]] = []
        if w_tmdb > 0:
            trending_base = await _fetch_tmdb_trending_candidates(
                allowed_langs=allowed_langs,
                fav_genres=fav_genres_all,
                block_ids=block_ids,
                limit=limit,
            )
            trending_cap = min(max(5, int(limit * 0.15)), 12)
            trending_base = trending_base[:trending_cap]
        # Improvement #9: Merge & combine scores from multiple sources (not overwrite)
        by_id: Dict[int, Dict[str, Any]] = {}
        for item in trending_base:
            tid = item["tmdb_id"]
            if tid not in by_id:
                by_id[tid] = {"tmdb_id": tid, "scores_by_source": {}, "source": item.get("source", "tmdb_trending")}
            by_id[tid]["scores_by_source"]["tmdb_trending"] = float(item.get("score_raw", 0.0))
        for item in tmdb_base:
            tid = item["tmdb_id"]
            if tid not in by_id:
                by_id[tid] = {"tmdb_id": tid, "scores_by_source": {}, "source": item.get("source", "tmdb_recs")}
            by_id[tid]["scores_by_source"]["tmdb_recs"] = float(item.get("score_raw", 0.0))
            # Prefer tmdb_recs as primary source label
            by_id[tid]["source"] = "tmdb_recs"
        for item in reddit_base:
            tid = item["tmdb_id"]
            if tid not in by_id:
                by_id[tid] = {"tmdb_id": tid, "scores_by_source": {}, "source": item.get("source", "reddit_pairs")}
            by_id[tid]["scores_by_source"]["reddit_pairs"] = float(item.get("score_raw", 0.0))
            # If reddit is the only source, keep it; otherwise multi-signal
            if len(by_id[tid]["scores_by_source"]) == 1:
                by_id[tid]["source"] = "reddit_pairs"
            else:
                by_id[tid]["source"] = "multi_signal"
        # Compute combined score_raw: sum of all source scores (multi-signal reinforcement)
        for tid, entry in by_id.items():
            scores = entry.get("scores_by_source", {})
            entry["score_raw"] = sum(scores.values())
        # Improvement #5: Remove hardcoded forced queries. Instead, use genre-cluster
        # seeding from TMDB discover (placeholder — kept minimal for drop-in compat).
        # The old "Pluribus" / "The Mighty Nein" logic is removed.
        base = list(by_id.values())
        if not base:
            if flat:
                return []
            return {
                "items": [],
                "meta": {
                    "user_id": user_id,
                    "n_candidates": 0,
                    "n_favorites": len(fav_ids),
                    "w_tmdb": w_tmdb,
                    "w_reddit": w_reddit,
                    "w_personal": w_personal,
                    "mmr_lambda": mmr_lambda,
                    "reason": "no_candidates",
                },
            }
        # Fetch TMDB details for candidates (batched — Improvement #1 already done here)
        tmdb_ids = [b["tmdb_id"] for b in base]
        details_list = await asyncio.gather(*[_tmdb_details(tid) for tid in tmdb_ids])
        quality_cfg = _quality_cfg_from_request()
        # Merge base scores + details, applying language + genre filters
        items: List[Dict[str, Any]] = []
        for base_item, det in zip(base, details_list):
            merged = dict(det or {})
            merged.setdefault("tmdb_id", base_item["tmdb_id"])
            merged["score_raw"] = float(base_item.get("score_raw") or 0.0)
            merged["source"] = base_item.get("source", "reddit_pairs")
            merged["scores_by_source"] = base_item.get("scores_by_source", {})
            lang = merged.get("original_language")
            if allowed_langs and lang and lang not in allowed_langs:
                continue
            genre_ids = merged.get("genre_ids") or []
            gid_set = set(int(g) for g in genre_ids if isinstance(g, int))
            if 10767 in gid_set or 10766 in gid_set:
                continue
            if excluded_genres and gid_set and gid_set.issubset(excluded_genres):
                continue
            if not _passes_quality_filter(merged, **quality_cfg):
                continue
            items.append(merged)
        # Fallback if filters removed everything
        if not items:
            for base_item, det in zip(base, details_list):
                merged = dict(det or {})
                merged.setdefault("tmdb_id", base_item["tmdb_id"])
                merged["score_raw"] = float(base_item.get("score_raw") or 0.0)
                merged["source"] = base_item.get("source", "reddit_pairs")
                merged["scores_by_source"] = base_item.get("scores_by_source", {})
                genre_ids = merged.get("genre_ids") or []
                gid_set = set(int(g) for g in genre_ids if isinstance(g, int))
                if 10767 in gid_set or 10766 in gid_set:
                    continue
                if excluded_genres and gid_set and gid_set.issubset(excluded_genres):
                    continue
                items.append(merged)
        # Build score vectors
        reddit_vals: List[float] = []
        tmdb_vals: List[float] = []
        personal_raw_vals: List[float] = []
        for it in items:
            try:
                raw = float(it.get("score_raw") or 0.0)
            except Exception:
                raw = 0.0
            reddit_vals.append(math.log10(1.0 + max(raw, 0.0)))
            tmdb_vals.append(_tmdb_quality(it))
            # Improvement #7: Use weighted Jaccard for favourite similarity
            if fav_details:
                best_sim = max(_similarity(it, f, fav_genre_counts) for f in fav_details)
            else:
                best_sim = 0.0
            genre_ids = it.get("genre_ids") or []
            cand_gids = [int(g) for g in genre_ids if isinstance(g, int)]
            if fav_genre_counts and cand_gids:
                num = sum(fav_genre_counts.get(g, 0) for g in cand_gids)
                denom = fav_genre_norm * math.sqrt(len(cand_gids) or 1)
                taste_sim = num / denom if denom > 0 else 0.0
            else:
                taste_sim = 0.0
            taste_sim = float(max(0.0, min(taste_sim, 1.0)))
            personal_raw = 0.7 * best_sim + 0.3 * taste_sim
            it["fav_similarity"] = best_sim
            it["taste_profile_sim"] = taste_sim
            personal_raw_vals.append(personal_raw)
        reddit_norm = _normalise(reddit_vals)
        tmdb_norm = _normalise(tmdb_vals)
        personal_norm = _normalise(personal_raw_vals)
        # Weighting
        total_w = w_tmdb + w_reddit + w_personal
        if total_w <= 0:
            w_reddit = 1.0
            w_tmdb = 0.0
            w_personal = 0.0
            total_w = 1.0
        scale = 1.0 / total_w
        w_tmdb_eff = w_tmdb * scale
        w_reddit_eff = w_reddit * scale
        w_personal_eff = w_personal * scale
        combined_items: List[Dict[str, Any]] = []
        for it, r_n, t_n, p_n in zip(items, reddit_norm, tmdb_norm, personal_norm):
            score_reddit = r_n
            score_tmdb = t_n
            score_personal = p_n
            score = (w_reddit_eff * score_reddit) + (w_tmdb_eff * score_tmdb) + (w_personal_eff * score_personal)
            # Favourite anchor boost
            if fav_anchor_boost > 0:
                try:
                    fs = float(it.get("fav_similarity", 0.0) or 0.0)
                except Exception:
                    fs = 0.0
                if fs > 0:
                    fs = max(0.0, min(1.0, fs))
                    score *= (1.0 + (fav_anchor_boost * fs))
            # Improvement #8: Exponential temporal decay instead of binary boost
            if freshness_boost:
                d = it.get("first_air_date") or ""
                year = None
                if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
                    year = int(d[:4])
                if year is not None:
                    age_years = max(0, now_year - year)
                    decay = math.exp(-0.1 * age_years)  # smooth exponential falloff
                    score *= (1.0 + (0.20 * decay))
            # Improvement #9: Multi-signal reinforcement bonus
            sources = it.get("scores_by_source", {})
            if len(sources) >= 2:
                # Items appearing in multiple sources get a small boost
                score *= (1.0 + 0.05 * (len(sources) - 1))
            enriched = dict(it)
            enriched["score_reddit"] = score_reddit
            enriched["score_tmdb"] = score_tmdb
            enriched["score_personal"] = score_personal
            enriched["score"] = score
            enriched["score_weights"] = {"tmdb": w_tmdb_eff, "reddit": w_reddit_eff, "personal": w_personal_eff}
            enriched["n_sources"] = len(sources)
            combined_items.append(enriched)
        # Diversity (MMR) + final top-N
        if 0.0 < mmr_lambda < 1.0:
            diversified = _mmr_diversify(combined_items, k=limit, mmr_lambda=mmr_lambda)
        else:
            diversified = sorted(combined_items, key=lambda x: float(x.get("score", 0.0)), reverse=True)[:limit]
        if recent_first and not freshness_boost:
            diversified = _recent_first_bucket(diversified, years=int(recent_years))
        # Clean up internal fields before returning
        for item in diversified:
            item.pop("scores_by_source", None)
        if flat:
            return diversified
        return {
            "items": diversified,
            "meta": {
                "user_id": user_id,
                "n_candidates": len(items),
                "n_favorites": len(fav_ids),
                "w_tmdb": w_tmdb,
                "w_reddit": w_reddit,
                "w_personal": w_personal,
                "mmr_lambda": mmr_lambda,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        try:
            print("recs_v3 exception:", repr(e), flush=True)
        except Exception:
            pass
        log.exception("recs_v3 failed user_id=%s limit=%s flat=%s", user_id, limit, flat)
        raise HTTPException(status_code=500, detail="Internal error in recs_v3")
@router.get("/explain/{user_id}/{tmdb_id}")
async def explain_recs_v3_for_show(
    user_id: int,
    tmdb_id: int,
    _: Any = Depends(require_user_match),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """Explain why recs_v3 thinks this show fits the user's taste."""
    if user_id <= 0 or tmdb_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid user_id or tmdb_id")
    try:
        fav_ids = await _fetch_user_favorites(session, user_id)
        target = await _tmdb_details(tmdb_id)
        target_genres = set(target.get("genres") or [])
        if not fav_ids:
            lines: List[str] = []
            if target_genres:
                top_g = ", ".join(list(target_genres)[:3])
                lines.append(f"Shares similar genres like {top_g}.")
            vote = target.get("vote_average")
            if isinstance(vote, (int, float)):
                if vote >= 8.5:
                    lines.append("Highly rated by other viewers.")
                elif vote >= 7.5:
                    lines.append("Well rated and liked by most audiences.")
            if not lines:
                lines.append("We don't have enough favourites for you yet, but this show aligns well with your overall taste profile.")
            return {
                "tmdb_id": tmdb_id,
                "user_id": user_id,
                "anchor_favorites": [],
                "shared_genres": sorted(target_genres),
                "reddit_pairs_strength": {"count": 0, "max": 0.0, "avg": 0.0},
                "tmdb_similarity": {"count": 0, "max": 0.0, "avg": 0.0},
                "summary_lines": lines,
            }
        sql = text(
            """
            SELECT
                CASE
                    WHEN tmdb_id_a = :tid THEN tmdb_id_b
                    ELSE tmdb_id_a
                END AS other_id,
                pair_weight
            FROM reddit_pairs
            WHERE tmdb_id_a = :tid OR tmdb_id_b = :tid
            """
        )
        res = await session.execute(sql, {"tid": tmdb_id})
        rows = res.mappings().all()
        pair_by_other: Dict[int, float] = {}
        for r in rows:
            other = r.get("other_id")
            if other is None:
                continue
            try:
                o_id = int(other)
            except Exception:
                continue
            w = r.get("pair_weight") or 0.0
            try:
                w_f = float(w)
            except Exception:
                w_f = 0.0
            prev = pair_by_other.get(o_id, 0.0)
            if w_f > prev:
                pair_by_other[o_id] = w_f
        fav_subset = fav_ids[: min(len(fav_ids), 30)]
        # Improvement #1: Already batched with asyncio.gather
        results = await asyncio.gather(*[_tmdb_details(fid) for fid in fav_subset], return_exceptions=True)
        anchors: List[Dict[str, Any]] = []
        for fav_id, det in zip(fav_subset, results):
            if isinstance(det, Exception):
                continue
            details = det or {}
            details.setdefault("tmdb_id", fav_id)
            title = details.get("title") or details.get("name")
            if not title:
                continue
            sim = _similarity(target, details)
            pair_w = pair_by_other.get(fav_id, 0.0)
            if sim <= 0.0 and pair_w <= 0.0:
                continue
            fav_genres = set(details.get("genres") or [])
            shared_genres = sorted(target_genres & fav_genres)
            anchors.append(
                {
                    "tmdb_id": fav_id,
                    "title": title,
                    "poster_path": details.get("poster_path"),
                    "poster_url": details.get("poster_url"),
                    "similarity": float(sim),
                    "pair_weight": float(pair_w),
                    "shared_genres": shared_genres,
                }
            )
        if not anchors:
            lines: List[str] = []
            if target_genres:
                top_g = ", ".join(list(target_genres)[:3])
                lines.append(f"Shares similar genres like {top_g}.")
            vote = target.get("vote_average")
            if isinstance(vote, (int, float)):
                if vote >= 8.5:
                    lines.append("Highly rated by other viewers.")
                elif vote >= 7.5:
                    lines.append("Well rated and liked by most audiences.")
            if not lines:
                lines.append("This show overlaps with your favourites in more subtle ways, even if we can't pinpoint a single anchor show.")
            return {
                "tmdb_id": tmdb_id,
                "user_id": user_id,
                "anchor_favorites": [],
                "shared_genres": sorted(target_genres),
                "reddit_pairs_strength": {"count": 0, "max": 0.0, "avg": 0.0},
                "tmdb_similarity": {"count": 0, "max": 0.0, "avg": 0.0},
                "summary_lines": lines,
            }
        def _combined_score(a: Dict[str, Any]) -> float:
            sim_val = float(a.get("similarity") or 0.0)
            pw_val = float(a.get("pair_weight") or 0.0)
            pw_term = math.log10(1.0 + max(pw_val, 0.0))
            return 0.7 * sim_val + 0.3 * pw_term
        anchors_sorted = sorted(anchors, key=_combined_score, reverse=True)
        top_anchors = anchors_sorted[:3]
        shared_genres_set: set[str] = set()
        sims_top: List[float] = []
        pair_top: List[float] = []
        for a in top_anchors:
            for g in a.get("shared_genres") or []:
                if isinstance(g, str) and g:
                    shared_genres_set.add(g)
            sims_top.append(float(a.get("similarity") or 0.0))
            pw_val = float(a.get("pair_weight") or 0.0)
            if pw_val > 0.0:
                pair_top.append(pw_val)
        shared_genres = sorted(shared_genres_set)
        tmdb_meta = {
            "count": len(sims_top),
            "max": max(sims_top) if sims_top else 0.0,
            "avg": (sum(sims_top) / len(sims_top)) if sims_top else 0.0,
        }
        reddit_meta = {
            "count": len(pair_top),
            "max": max(pair_top) if pair_top else 0.0,
            "avg": (sum(pair_top) / len(pair_top)) if pair_top else 0.0,
        }
        summary_lines: List[str] = []
        anchor_titles = [str(a.get("title")).strip() for a in top_anchors if a.get("title")]
        if anchor_titles:
            if len(anchor_titles) == 1:
                summary_lines.append(f"Because you liked {anchor_titles[0]}.")
            elif len(anchor_titles) == 2:
                summary_lines.append(f"Because you liked {anchor_titles[0]} and {anchor_titles[1]}.")
            else:
                summary_lines.append(f"Because you liked {anchor_titles[0]}, {anchor_titles[1]} and {anchor_titles[2]}.")
        if shared_genres:
            if len(shared_genres) == 1:
                summary_lines.append(f"Shares a strong {shared_genres[0]} vibe.")
            else:
                top_g = ", ".join(shared_genres[:3])
                summary_lines.append(f"Shares genres like {top_g}.")
        if reddit_meta["count"] > 0:
            summary_lines.append("These shows are often discussed together on Reddit, so they tend to appeal to similar audiences.")
        vote = target.get("vote_average")
        if isinstance(vote, (int, float)):
            if vote >= 8.5:
                summary_lines.append("Highly rated by other viewers.")
            elif vote >= 7.5:
                summary_lines.append("Well rated and liked by most audiences.")
        if not summary_lines:
            summary_lines.append("This show overlaps strongly with your favourite shows in terms of tone and themes.")
        return {
            "tmdb_id": tmdb_id,
            "user_id": user_id,
            "anchor_favorites": top_anchors,
            "shared_genres": shared_genres,
            "reddit_pairs_strength": reddit_meta,
            "tmdb_similarity": tmdb_meta,
            "summary_lines": summary_lines,
        }
    except HTTPException:
        raise
    except Exception:
        log.exception("explain engine failed user_id=%s tmdb_id=%s", user_id, tmdb_id)
        raise HTTPException(status_code=500, detail="Internal error in explanation engine")
@router.get("/smart-similar/{tmdb_id}")
async def get_smart_similar_for_show(
    tmdb_id: int,
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """
    Improvement #1 & #10: Batched TMDB calls + blended reddit_pairs signal.
    """
    api_key = _tmdb_api_key()
    if not api_key:
        return []
    try:
        # Fetch TMDB recs + reddit pairs in parallel
        tmdb_task = _tmdb_recommendations_for_fav(tmdb_id, api_key, max_n=limit * 2)
        # Improvement #10: Also pull reddit_pairs for this show (no user needed)
        reddit_sql = text(
            """
            SELECT
                CASE
                    WHEN tmdb_id_a = :tid THEN tmdb_id_b
                    ELSE tmdb_id_a
                END AS other_id,
                pair_weight
            FROM reddit_pairs
            WHERE tmdb_id_a = :tid OR tmdb_id_b = :tid
            ORDER BY pair_weight DESC NULLS LAST
            LIMIT :lim
            """
        )
        async def _fetch_reddit_similar():
            try:
                res = await session.execute(reddit_sql, {"tid": tmdb_id, "lim": limit * 2})
                rows = res.mappings().all()
                return {int(r["other_id"]): float(r.get("pair_weight", 0.0)) for r in rows if r.get("other_id") is not None}
            except Exception:
                return {}
        rec_ids_raw, reddit_scores = await asyncio.gather(tmdb_task, _fetch_reddit_similar(), return_exceptions=False)
        # Merge: TMDB recs get base score 0.6, reddit pairs get their weight
        merged_scores: Dict[int, float] = {}
        for rid in (rec_ids_raw or []):
            if not isinstance(rid, int) or rid == tmdb_id:
                continue
            merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.6
        for rid, pw in (reddit_scores or {}).items():
            if rid == tmdb_id:
                continue
            reddit_score = 0.4 * math.log10(1.0 + max(pw, 0.0))
            merged_scores[rid] = merged_scores.get(rid, 0.0) + reddit_score
        # Sort by combined score
        sorted_ids = sorted(merged_scores.keys(), key=lambda x: merged_scores[x], reverse=True)
        # Improvement #1: Batch fetch details
        fetch_ids = sorted_ids[: limit * 2]
        details_list = await asyncio.gather(*[_tmdb_details(rid) for rid in fetch_ids])
        items: list[dict[str, Any]] = []
        for details in details_list:
            title = details.get("title") or details.get("name")
            if not title:
                continue
            items.append(details)
            if len(items) >= limit:
                break
        return items
    except HTTPException:
        raise
    except Exception:
        log.exception("smart-similar failed tmdb_id=%s", tmdb_id)
        raise HTTPException(status_code=500, detail="Internal error in smart-similar")