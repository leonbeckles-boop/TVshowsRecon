from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.security import require_user_match

TMDB_API = os.environ.get("TMDB_API", "https://api.themoviedb.org/3")
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

router = APIRouter(prefix="/recs/v3", tags=["recs_v3"])

log = logging.getLogger("recs_v3")

# Require at least this many favourites before we serve any recs
MIN_FAVORITES = 3


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
    Returns a dict with the same shape v1/v2 use:
      tmdb_id, name/title, overview, poster_path/url, genres, genre_ids, etc.
    """
    api_key = _tmdb_api_key()
    if not api_key:
        return {"tmdb_id": tmdb_id}

    url = f"{TMDB_API}/tv/{tmdb_id}?api_key={api_key}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
    except Exception:
        # Network error – return minimal
        return {"tmdb_id": tmdb_id}

    if r.status_code != 200:
        return {"tmdb_id": tmdb_id}

    data = r.json() or {}

    poster_path = (data.get("poster_path") or "").lstrip("/")
    poster_url = f"{TMDB_IMG}/{poster_path}" if poster_path else None

    genres_arr = data.get("genres") or []
    genre_names = [str(g.get("name")).strip() for g in genres_arr if g and g.get("name")]

    # TMDB genre ids are ints, but keep the guard anyway
    genre_ids: list[int] = []
    for g in genres_arr:
        if not g:
            continue
        gid = g.get("id")
        if isinstance(gid, int):
            genre_ids.append(gid)

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
        "genres": genre_names,
        "genre_ids": genre_ids,
        "vote_average": data.get("vote_average"),
        "vote_count": data.get("vote_count"),
        "popularity": data.get("popularity"),
    }


async def _tmdb_recommendations_for_fav(tmdb_id: int, api_key: str, max_n: int = 20) -> List[int]:
    """
    Fetch TMDB recommendations for a single favourite show.
    Returns a list of recommended tmdb_ids (TV).
    """
    url = f"{TMDB_API}/tv/{tmdb_id}/recommendations?api_key={api_key}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
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

    # Limit how many favourites we query to avoid spamming TMDB
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

    Returns [{ tmdb_id, score_raw, source="tmdb_trending" }, ...].
    """
    api_key = _tmdb_api_key()
    if not api_key:
        return []

    url = f"{TMDB_API}/trending/tv/week?api_key={api_key}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
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

        # Drop Talk / Soap
        if 10767 in gid_set or 10766 in gid_set:
            continue

        # Require at least one overlapping genre if we have a profile
        if fav_genres and not (fav_genres & gid_set):
            continue

        pop = row.get("popularity") or 0.0
        try:
            pop = float(pop)
        except Exception:
            pop = 0.0

        base = math.log10(1.0 + max(pop, 0.0))
        score_raw = 0.3 + 0.4 * base  # trending should be a nudge

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
        """
    )
    res = await session.execute(sql, {"uid": user_id})
    rows = res.mappings().all()
    return {int(r["tmdb_id"]) for r in rows if r.get("tmdb_id") is not None}


async def _fetch_user_favorites(session: AsyncSession, user_id: int) -> List[int]:
    """
    Return list of tmdb_ids the user has marked as favourites.
    """
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

# ---------------------------------------------------------------------------
# Semantic (pgvector) helpers
# ---------------------------------------------------------------------------

EMBED_DIM = 384  # you migrated show_embeddings/user_profiles to vector(384)

def _vec_to_pgvector_literal(vec: List[float]) -> str:
    """
    pgvector accepts '[0.1,0.2,...]' string literal.
    Keep it compact + deterministic.
    """
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _avg_vectors(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    n = 0
    for v in vectors:
        if not v or len(v) != dim:
            continue
        for i, x in enumerate(v):
            out[i] += float(x)
        n += 1
    if n <= 0:
        return []
    inv = 1.0 / n
    return [x * inv for x in out]


async def _fetch_embeddings_for_tmdb_ids(
    session: AsyncSession,
    tmdb_ids: List[int],
) -> List[List[float]]:
    """
    Pull embeddings for a list of TMDB ids from show_embeddings.
    Returns list of vectors (python lists).
    """
    if not tmdb_ids:
        return []

    sql = text("""
        SELECT tmdb_id, embedding
        FROM show_embeddings
        WHERE tmdb_id IN :ids
    """).bindparams(bindparam("ids", expanding=True))


    res = await session.execute(sql, {"ids": tmdb_ids})
    rows = res.mappings().all()

    vectors: List[List[float]] = []
    for r in rows:
        emb = r.get("embedding")
        if emb is None:
            continue
        # pgvector usually comes back as list-like already; keep it defensive
        try:
            vec = list(emb)
            if vec:
                vectors.append([float(x) for x in vec])
        except Exception:
            continue
    return vectors


async def _user_profile_embedding_from_favs(session: AsyncSession, fav_ids: List[int]) -> List[float]:
    """
    Simple user profile embedding = mean of favourite show embeddings.
    """
    vecs = await _fetch_embeddings_for_tmdb_ids(session, fav_ids)
    return _avg_vectors(vecs)


async def _semantic_candidates(
    session: AsyncSession,
    user_vec: List[float],
    block_ids: set[int],
    limit: int,
) -> Dict[int, float]:
    """
    Return {tmdb_id: semantic_sim} where semantic_sim is ~0..1.
    Uses cosine distance (<=>). Similarity = 1 - distance.
    """
    if not user_vec:
        return {}

    # Overfetch to allow later dedupe/filtering
    raw_limit = max(limit * 6, limit * 3, limit)

    vlit = _vec_to_pgvector_literal(user_vec)

    sql = text(
        """
        SELECT tmdb_id, (embedding <=> (:v)::vector) AS dist
        FROM show_embeddings
        ORDER BY embedding <=> (:v)::vector ASC
        LIMIT :lim
        """
    )

    res = await session.execute(sql, {"v": vlit, "lim": raw_limit})
    rows = res.mappings().all()

    out: Dict[int, float] = {}
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

        dist = r.get("dist")
        try:
            d = float(dist)
        except Exception:
            d = 1.0

        # cosine distance is 0..2 (usually 0..1-ish when normalized); clamp anyway
        sim = 1.0 - d
        if sim < 0.0:
            sim = 0.0
        if sim > 1.0:
            sim = 1.0

        # keep best (closest) only
        prev = out.get(tid_i)
        if prev is None or sim > prev:
            out[tid_i] = sim

    return out



async def _fetch_reddit_candidates_from_pairs(
    session: AsyncSession,
    fav_ids: List[int],
    limit: int,
    block_ids: set[int],
) -> List[Dict[str, Any]]:
    """
    Build reddit candidates using the existing global reddit_pairs table,
    using the user's favourites as anchors.

    This replaces the old user_reddit_pairs dependency (which may not exist).
    """
    if not fav_ids:
        return []

    raw_limit = max(limit * 6, limit * 3, limit)

    # We use expanding IN (...) params to avoid asyncpg ARRAY/ANY edge cases.
    sql = text(
        """
        SELECT
            CASE
                WHEN rp.tmdb_id_a IN (:favs) THEN rp.tmdb_id_b
                ELSE rp.tmdb_id_a
            END AS tmdb_id,
            SUM(rp.pair_weight) AS weight
        FROM reddit_pairs rp
        WHERE (rp.tmdb_id_a IN (:favs) OR rp.tmdb_id_b IN (:favs))
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
    except Exception as e:
        print("reddit_pairs query failed; skipping reddit candidates:", repr(e))
        await session.rollback()   # <<< CRITICAL
        return []

    rows = res.mappings().all()
    items: List[Dict[str, Any]] = []

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
        try:
            w_f = float(w)
        except Exception:
            w_f = 0.0
        if w_f <= 0:
            continue

        items.append({"tmdb_id": tid_i, "score_raw": w_f, "source": "reddit_pairs"})

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
    """
    TMDB quality heuristic.

    - confidence-adjusted rating (vote_average + vote_count)
    - plus log-squashed popularity bonus
    """
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


def _similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """
    Similarity used for both MMR and favourite-similarity:
      - Jaccard over genre_ids
      - small bonus if language matches
    """
    ga = set(a.get("genre_ids") or [])
    gb = set(b.get("genre_ids") or [])
    if not ga or not gb:
        base = 0.0
    else:
        inter = len(ga & gb)
        union = len(ga | gb) or 1
        base = inter / union

        # Penalise very weak matches (only 1 overlapping genre)
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


@router.get("/{user_id}")
async def get_recs_v3(
    user_id: int,
    limit: int = Query(36, ge=1, le=200),
    w_tmdb: float = Query(0.5, ge=0.0, le=1.0),
    w_reddit: float = Query(0.5, ge=0.0, le=1.0),
    w_personal: float = Query(0.3, ge=0.0, le=1.0),
    w_semantic: float = Query(0.25, ge=0.0, le=1.0),
    mmr_lambda: float = Query(0.3, ge=0.0, le=1.0),
    flat: int = Query(0),
    _: Any = Depends(require_user_match),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """
    v3 recommendations:
      - candidates from:
          * reddit_pairs (global) anchored on user favourites
          * TMDB /tv/{fav}/recommendations for user's favourites
          * TMDB /trending/tv/week filtered by user's taste
      - filter out favourites + not-interested
      - fetch TMDB details
      - build a 'taste vector' from favourites (genres + language)
      - compute:
          * score_reddit   (log weight)
          * score_tmdb     (quality)
          * score_personal (favourite-similarity + profile similarity)
      - combine with weights + optional MMR diversity
    """
    try:
        # 1) Blocked IDs (favourites + not-interested)
        block_ids = await _get_block_ids(session, user_id)

        # 2) User favourites (for personalisation + TMDB recs/profile)
        fav_ids = await _fetch_user_favorites(session, user_id)

        # ---- Gate: require a minimum number of favourites ----
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

        # 3) Reddit candidates (from global reddit_pairs anchored on favourites)
        reddit_base = await _fetch_reddit_candidates_from_pairs(session, fav_ids, limit, block_ids)

        # 4) Favourite details for language/genre profile
        fav_details:  List[Dict[str, Any]] = await asyncio.gather(*[_tmdb_details(fid) for fid in fav_ids])

        # 4b) Semantic profile + semantic candidates (pgvector)
        user_vec = await _user_profile_embedding_from_favs(session, fav_ids)
        semantic_map = await _semantic_candidates(session, user_vec, block_ids, limit)


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
        fav_genre_norm = math.sqrt(sum(c * c for c in fav_genre_counts.values())) or 1.0

        # 5) TMDB recs from favourites
        tmdb_base = await _fetch_tmdb_candidates(fav_ids, block_ids, limit)

        # 6) TMDB trending, filtered by taste
        trending_base = await _fetch_tmdb_trending_candidates(
            allowed_langs=allowed_langs,
            fav_genres=fav_genres_all,
            block_ids=block_ids,
            limit=limit,
        )

        # 7) Merge & dedupe by tmdb_id (priority: reddit > tmdb recs > trending)
        by_id: Dict[int, Dict[str, Any]] = {}

        for item in trending_base:
            by_id[item["tmdb_id"]] = item
        for item in tmdb_base:
            by_id[item["tmdb_id"]] = item
        for item in reddit_base:
            by_id[item["tmdb_id"]] = item

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

        # 8) Fetch TMDB details for candidates
        tmdb_ids = [b["tmdb_id"] for b in base]
        details_list = await asyncio.gather(*[_tmdb_details(tid) for tid in tmdb_ids])

        # 9) Merge base scores + details, applying language + genre filters
        items: List[Dict[str, Any]] = []
        for base_item, det in zip(base, details_list):
            merged = dict(det or {})
            merged.setdefault("tmdb_id", base_item["tmdb_id"])
            merged["score_raw"] = float(base_item.get("score_raw") or 0.0)
            merged["source"] = base_item.get("source", "reddit_pairs")
            merged["semantic_sim"] = float(semantic_map.get(int(merged["tmdb_id"]), 0.0))

            lang = merged.get("original_language")
            if allowed_langs and lang not in allowed_langs:
                continue

            genre_ids = merged.get("genre_ids") or []
            gid_set = set(int(g) for g in genre_ids if isinstance(g, int))

            # Drop Talk (10767) and Soap (10766)
            if 10767 in gid_set or 10766 in gid_set:
                continue

            items.append(merged)

        # If filters removed everything, fall back to unfiltered merged candidates
        if not items:
            for base_item, det in zip(base, details_list):
                merged = dict(det or {})
                merged.setdefault("tmdb_id", base_item["tmdb_id"])
                merged["score_raw"] = float(base_item.get("score_raw") or 0.0)
                merged["source"] = base_item.get("source", "reddit_pairs")
                merged["semantic_sim"] = float(semantic_map.get(int(merged["tmdb_id"]), 0.0))
                items.append(merged)

        # 10) Build Reddit + TMDB score vectors and personalisation
        reddit_vals: List[float] = []
        tmdb_vals: List[float] = []
        personal_raw_vals: List[float] = []
        semantic_vals: List[float] = []

        for it in items:
            # Reddit score: log-squashed score_raw
                        # Semantic similarity (already ~0..1)
            try:
                sem = float(it.get("semantic_sim") or 0.0)
            except Exception:
                sem = 0.0
            semantic_vals.append(max(0.0, min(sem, 1.0)))

            try:
                raw = float(it.get("score_raw") or 0.0)
            except Exception:
                raw = 0.0
            reddit_vals.append(math.log10(1.0 + max(raw, 0.0)))

            # TMDB quality
            tmdb_vals.append(_tmdb_quality(it))

            # Personalisation:
            #  (a) max similarity to any favourite
            if fav_details:
                best_sim = max(_similarity(it, f) for f in fav_details)
            else:
                best_sim = 0.0

            #  (b) taste-vector similarity (genre profile vs candidate genres)
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
            semantic_norm = _normalise(semantic_vals)

        # 11) Weighting
        total_w = w_tmdb + w_reddit + w_personal + w_semantic

        if total_w <= 0:
            w_reddit = 1.0
            w_tmdb = 0.0
            w_personal = 0.0
            total_w = 1.0

        scale = 1.0 / total_w
        w_tmdb_eff = w_tmdb * scale
        w_reddit_eff = w_reddit * scale
        w_personal_eff = w_personal * scale
        w_semantic_eff = w_semantic * scale

        combined_items: List[Dict[str, Any]] = []
        for it, r_n, t_n, p_n, s_n in zip(items, reddit_norm, tmdb_norm, personal_norm, semantic_norm):
            score_reddit = float(r_n or 0.0)
            score_tmdb = float(t_n or 0.0)
            score_personal = float(p_n or 0.0)
            score_semantic = float(s_n or 0.0)

            score = (
                (w_reddit_eff * score_reddit)
                + (w_tmdb_eff * score_tmdb)
                + (w_personal_eff * score_personal)
                + (w_semantic_eff * score_semantic)
            )

            enriched = dict(it)
            enriched["score_reddit"] = score_reddit
            enriched["score_tmdb"] = score_tmdb
            enriched["score_personal"] = score_personal
            enriched["score_semantic"] = score_semantic
            enriched["score"] = score
            enriched["score_weights"] = {
                "tmdb": w_tmdb_eff,
                "reddit": w_reddit_eff,
                "personal": w_personal_eff,
                "semantic": w_semantic_eff,
            }
            combined_items.append(enriched)
    

        try:
            from app.services.llm_rerank import rerank_candidates  # type: ignore
        except Exception:
            rerank_candidates = None

        if rerank_candidates is not None and len(combined_items) >= 5:
            # Sort by current blended score and rerank only the top slice
            combined_items = sorted(
                combined_items,
                key=lambda x: float(x.get("score", 0.0)),
                reverse=True,
            )

            top_n = min(len(combined_items), int(os.getenv("LLM_RERANK_CANDIDATES", "60")))
            top_slice = combined_items[:top_n]

            fav_titles = [
                d.get("title") or d.get("name")
                for d in fav_details
                if (d.get("title") or d.get("name"))
            ]

            order = rerank_candidates(favorite_titles=fav_titles, candidates=top_slice)

            if order:
                by_id = {int(x["tmdb_id"]): x for x in top_slice}
                reranked = [by_id[i] for i in order if i in by_id]
                combined_items = reranked + combined_items[top_n:]



        # 12) Diversity (MMR) + final top-N
        if 0.0 < mmr_lambda < 1.0:
            diversified = _mmr_diversify(combined_items, k=limit, mmr_lambda=mmr_lambda)
        else:
            diversified = sorted(combined_items, key=lambda x: float(x.get("score", 0.0)), reverse=True)[:limit]

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
                "w_semantic": w_semantic,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        # Ensure something shows up even if logging config is minimal on Render
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
    """
    Explain why recs_v3 thinks this show fits the user's taste.
    (Kept compatible with your existing FE usage.)
    """
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

        # Pull all reddit_pairs rows that involve this tmdb_id, then intersect with favourites.
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
) -> Any:
    """
    Lightweight show-centric smart similar endpoint, used by the ShowDetails page.
    Does not depend on a user_id.
    """
    api_key = _tmdb_api_key()
    if not api_key:
        return []

    try:
        rec_ids = await _tmdb_recommendations_for_fav(tmdb_id, api_key, max_n=limit * 2)
        if not rec_ids:
            return []

        seen: set[int] = set()
        ordered_ids: list[int] = []
        for rid in rec_ids:
            if not isinstance(rid, int):
                continue
            if rid == tmdb_id:
                continue
            if rid in seen:
                continue
            seen.add(rid)
            ordered_ids.append(rid)
            if len(ordered_ids) >= limit * 2:
                break

        items: list[dict[str, Any]] = []
        for rid in ordered_ids:
            details = await _tmdb_details(rid)
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
