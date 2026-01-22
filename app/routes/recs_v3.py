from __future__ import annotations

import asyncio
import math
import os
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.db.session import get_session_dep as get_session_dep
except ImportError:  # older name
    from app.db.session import get_async_db as get_session_dep
TMDB_API = os.environ.get("TMDB_API", "https://api.themoviedb.org/3")
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

router = APIRouter(prefix="/recs/v3", tags=["recs_v3"])

@router.get(
    "",
    summary="Get recommendations (v3) using query parameters",
    name="get_recs_v3_query",
)
async def get_recs_v3_query(
    user_id: int = Query(..., description="User id", alias="user_id"),
    limit: int = Query(60, ge=1, le=200),
    flat: int = Query(1, description="1 = flat list, 0 = grouped"),
    session = Depends(get_session_dep),
):
    # Delegate to the path-param endpoint for consistent logic
    return await get_recs_v3(user_id=user_id, limit=limit, flat=flat, session=session)


# Require at least this many favourites before we serve any recs
MIN_FAVORITES = 3


# ---------------------------------------------------------------------------
# TMDB helpers
# ---------------------------------------------------------------------------

async def _tmdb_details(tmdb_id: int) -> Dict[str, Any]:
    """
    Fetch TV details for a tmdb_id from TMDB.
    Returns a dict with the same shape v1/v2 use:
      tmdb_id, name/title, overview, poster_path/url, genres, genre_ids, etc.
    """
    api_key = (
        os.environ.get("TMDB_API_KEY")
        or os.environ.get("TMDB_KEY")
        or os.environ.get("TMDB_API")
    )
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
    genre_names = [
        str(g.get("name")).strip()
        for g in genres_arr
        if g and g.get("name")
    ]
    genre_ids = [
        int(g.get("id"))
        for g in genres_arr
        if g and isinstance(g.get("id"), int)
    ]

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


async def _tmdb_recommendations_for_fav(
    tmdb_id: int,
    api_key: str,
    max_n: int = 20,
) -> List[int]:
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


async def _fetch_tmdb_candidates(
    fav_ids: List[int],
    block_ids: set[int],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Build TMDB-based candidate list from favourites using /tv/{id}/recommendations.
    Returns [{ tmdb_id, score_raw, source="tmdb_recs" }, ...].
    """
    api_key = (
        os.environ.get("TMDB_API_KEY")
        or os.environ.get("TMDB_KEY")
        or os.environ.get("TMDB_API")
    )
    if not api_key or not fav_ids:
        return []

    # Limit how many favourites we query to avoid spamming TMDB
    max_favs = min(len(fav_ids), 10)
    fav_slice = fav_ids[:max_favs]

    tasks = [
        _tmdb_recommendations_for_fav(fid, api_key, max_n=20)
        for fid in fav_slice
    ]
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
        items.append(
            {
                "tmdb_id": tid,
                "score_raw": 1.0,
                "source": "tmdb_recs",
            }
        )
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
    api_key = (
        os.environ.get("TMDB_API_KEY")
        or os.environ.get("TMDB_KEY")
        or os.environ.get("TMDB_API")
    )
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

        # Base weight from popularity, but softer than reddit/TMDB recs
        # so trending is a "nudge", not the main driver.
        base = math.log10(1.0 + max(pop, 0.0))
        score_raw = 0.3 + 0.4 * base  # was 0.5 + 1.0 * base

        items.append(
            {
                "tmdb_id": tid,
                "score_raw": score_raw,
                "source": "tmdb_trending",
            }
        )
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
    return {int(r["tmdb_id"]) for r in rows}


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


async def _fetch_reddit_candidates(
    session: AsyncSession,
    user_id: int,
    limit: int,
    block_ids: set[int],
) -> List[Dict[str, Any]]:
    """
    Pull per-user reddit recs from user_reddit_pairs.
    Returns list[ { tmdb_id, score_raw } ], already filtered.
    """
    raw_limit = max(limit * 3, limit)

    sql = text(
        """
        SELECT suggested_tmdb_id AS tmdb_id, weight
        FROM user_reddit_pairs
        WHERE user_id = :uid
        ORDER BY weight DESC
        LIMIT :limit
        """
    )
    res = await session.execute(
        sql, {"uid": user_id, "limit": raw_limit}
    )
    rows = res.mappings().all()

    items: List[Dict[str, Any]] = []
    for r in rows:
        tid = int(r["tmdb_id"])
        if tid in block_ids:
            continue
        items.append(
            {
                "tmdb_id": tid,
                "score_raw": float(r["weight"] or 0.0),
                "source": "reddit_v3",
            }
        )
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
    TMDB quality heuristic:

    - IMDb-style confidence-adjusted rating:
        rating_conf = (v / (v + m)) * R + (m / (v + m)) * C
      where:
        R = vote_average
        v = vote_count
        C = global mean (e.g. 6.5)
        m = minimum votes threshold (e.g. 50)

    - plus a log-squashed popularity bonus:
        + 0.5 * log10(popularity + 1)
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
    'Similarity' used for both MMR and favourite-similarity:
      - Jaccard over genre_ids
      - extra weight only when there are 2+ overlapping genres
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
            # Slight boost when lots of genres line up
            base *= 1.1

    la = a.get("original_language")
    lb = b.get("original_language")
    if la and lb and la == lb:
        base += 0.1

    return float(max(0.0, min(base, 1.0)))


def _mmr_diversify(
    items: List[Dict[str, Any]],
    k: int,
    mmr_lambda: float,
) -> List[Dict[str, Any]]:
    """
    Basic MMR: greedily pick items maximising
      λ * relevance - (1-λ) * max_sim_to_selected
    where 'relevance' is item['score'].
    """
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
    mmr_lambda: float = Query(0.3, ge=0.0, le=1.0),
    flat: int = Query(0),
    session: AsyncSession = Depends(get_session_dep),
) -> Any:
    """
    v3 recommendations:
      - candidates from:
          * user_reddit_pairs (per-user reddit recs)
          * TMDB /tv/{fav}/recommendations for user's favourites
          * TMDB /trending/tv/week filtered by user's taste
      - filter out favourites + not-interested
      - fetch TMDB details
      - build a 'taste vector' from favourites (genres + language)
      - compute:
          * score_reddit   (log weight)
          * score_tmdb     (quality)
          * score_personal (favourite-similarity + profile similarity)
      - drop Talk / Soap & off-language content
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

        # 3) Per-user Reddit candidates
        reddit_base = await _fetch_reddit_candidates(session, user_id, limit, block_ids)

        # 4) Favourite details for language/genre profile
        fav_details: List[Dict[str, Any]] = []
        if fav_ids:
            fav_details = await asyncio.gather(
                *[_tmdb_details(fid) for fid in fav_ids]
            )

        # Language profile
        allowed_langs = {
            d.get("original_language")
            for d in fav_details
            if d.get("original_language")
        }

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
        fav_genre_norm = math.sqrt(
            sum(c * c for c in fav_genre_counts.values())
        ) or 1.0

        # 5) TMDB recs from favourites
        tmdb_base = await _fetch_tmdb_candidates(fav_ids, block_ids, limit)

        # 6) TMDB trending, filtered by taste
        trending_base = await _fetch_tmdb_trending_candidates(
            allowed_langs=allowed_langs,
            fav_genres=fav_genres_all,
            block_ids=block_ids,
            limit=limit,
        )

        # 7) Merge & dedupe by tmdb_id
        by_id: Dict[int, Dict[str, Any]] = {}

        # Lowest priority: trending
        for item in trending_base:
            by_id[item["tmdb_id"]] = item

        # Override with TMDB recs
        for item in tmdb_base:
            by_id[item["tmdb_id"]] = item

        # Highest priority: reddit
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
                },
            }

        # 8) Fetch TMDB details for candidates
        tmdb_ids = [b["tmdb_id"] for b in base]
        details_list = await asyncio.gather(
            *[_tmdb_details(tid) for tid in tmdb_ids]
        )

        # 9) Merge base scores + details, applying language + genre filters
        items: List[Dict[str, Any]] = []

        for base_item, det in zip(base, details_list):
            merged = dict(det)
            merged.setdefault("tmdb_id", base_item["tmdb_id"])
            merged["score_raw"] = float(base_item.get("score_raw") or 0.0)
            merged["source"] = base_item.get("source", "reddit_v3")

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
                merged = dict(det)
                merged.setdefault("tmdb_id", base_item["tmdb_id"])
                merged["score_raw"] = float(base_item.get("score_raw") or 0.0)
                merged["source"] = base_item.get("source", "reddit_v3")
                items.append(merged)

        # 10) Build Reddit + TMDB score vectors and personalisation
        reddit_vals: List[float] = []
        tmdb_vals: List[float] = []
        personal_raw_vals: List[float] = []

        for it in items:
            # Reddit score: log-squashed score_raw
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

            # Combine into a raw personal signal
            personal_raw = 0.7 * best_sim + 0.3 * taste_sim

            it["fav_similarity"] = best_sim
            it["taste_profile_sim"] = taste_sim

            personal_raw_vals.append(personal_raw)

        reddit_norm = _normalise(reddit_vals)
        tmdb_norm = _normalise(tmdb_vals)
        personal_norm = _normalise(personal_raw_vals)

        # 11) Weighting
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

            score = (
                w_reddit_eff * score_reddit
                + w_tmdb_eff * score_tmdb
                + w_personal_eff * score_personal
            )

            enriched = dict(it)
            enriched["score_reddit"] = score_reddit
            enriched["score_tmdb"] = score_tmdb
            enriched["score_personal"] = score_personal
            enriched["score"] = score
            enriched["score_weights"] = {
                "tmdb": w_tmdb_eff,
                "reddit": w_reddit_eff,
                "personal": w_personal_eff,
            }
            combined_items.append(enriched)

        # 12) Diversity (MMR) + final top-N
        if 0.0 < mmr_lambda < 1.0:
            diversified = _mmr_diversify(combined_items, k=limit, mmr_lambda=mmr_lambda)
        else:
            diversified = sorted(
                combined_items,
                key=lambda x: float(x.get("score", 0.0)),
                reverse=True,
            )[:limit]

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
    except Exception:
        raise HTTPException(status_code=500, detail="Internal error in recs_v3")

@router.get("/explain/{user_id}/{tmdb_id}")
async def explain_recs_v3_for_show(
    user_id: int,
    tmdb_id: int,
    session: AsyncSession = Depends(get_session_dep),
) -> Dict[str, Any]:
    """
    Explain why recs_v3 thinks this show fits the user's taste.

    Uses the same building blocks as the main v3 engine:
      - user favourites
      - TMDB-based similarity (genres + language)
      - reddit_pairs co-mention strength

    Returns a small JSON payload with:
      - anchor_favorites: the key favourites that 'explain' this show
      - shared_genres: overlapping genre names across anchors
      - reddit_pairs_strength: simple stats over pair_weight vs anchors
      - tmdb_similarity: simple stats over similarity vs anchors
      - summary_lines: human-readable bullet points
    """
    if user_id <= 0 or tmdb_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid user_id or tmdb_id")

    try:
        # Fetch favourites for this user
        fav_ids = await _fetch_user_favorites(session, user_id)

        # Always fetch target details so we can at least fall back to a simple explanation.
        target = await _tmdb_details(tmdb_id)
        target_genres = set(target.get("genres") or [])

        # No favourites => fall back to a generic, show-only explanation
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
                lines.append(
                    "We don't have enough favourites for you yet, but this show aligns well with your overall taste profile."
                )
            return {
                "tmdb_id": tmdb_id,
                "user_id": user_id,
                "anchor_favorites": [],
                "shared_genres": sorted(target_genres),
                "reddit_pairs_strength": {
                    "count": 0,
                    "max": 0.0,
                    "avg": 0.0,
                },
                "tmdb_similarity": {
                    "count": 0,
                    "max": 0.0,
                    "avg": 0.0,
                },
                "summary_lines": lines,
            }

        # Pull all reddit_pairs rows that involve this tmdb_id, then later intersect with favourites.
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
            # Keep the strongest weight we see for a given other_id
            prev = pair_by_other.get(o_id, 0.0)
            if w_f > prev:
                pair_by_other[o_id] = w_f

        # Limit how many favourites we consider for explanation to keep TMDB calls bounded.
        max_favs = min(len(fav_ids), 30)
        fav_subset = fav_ids[:max_favs]

        # Fetch TMDB details for favourite subset concurrently.
        tasks = [_tmdb_details(fid) for fid in fav_subset]
        results = await asyncio.gather(*tasks, return_exceptions=True)

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

            # If we have neither similarity nor reddit signal, this favourite doesn't help explain much.
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
            # User has favourites, but none with meaningful overlap or reddit signal.
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
                lines.append(
                    "This show overlaps with your favourites in more subtle ways, even if we can't pinpoint a single anchor show."
                )
            return {
                "tmdb_id": tmdb_id,
                "user_id": user_id,
                "anchor_favorites": [],
                "shared_genres": sorted(target_genres),
                "reddit_pairs_strength": {
                    "count": 0,
                    "max": 0.0,
                    "avg": 0.0,
                },
                "tmdb_similarity": {
                    "count": 0,
                    "max": 0.0,
                    "avg": 0.0,
                },
                "summary_lines": lines,
            }

        # Rank anchors by a combined score of TMDB similarity and reddit_pairs weight.
        def _combined_score(a: Dict[str, Any]) -> float:
            sim_val = float(a.get("similarity") or 0.0)
            pw_val = float(a.get("pair_weight") or 0.0)
            pw_term = math.log10(1.0 + max(pw_val, 0.0))
            return 0.7 * sim_val + 0.3 * pw_term

        anchors_sorted = sorted(anchors, key=_combined_score, reverse=True)
        max_anchors = 3
        top_anchors = anchors_sorted[:max_anchors]

        # Aggregate shared genres and stats based only on top anchors.
        shared_genres_set: set[str] = set()
        sims_top: List[float] = []
        pair_top: List[float] = []

        for a in top_anchors:
            for g in a.get("shared_genres") or []:
                if isinstance(g, str) and g:
                    shared_genres_set.add(g)
            sim_val = float(a.get("similarity") or 0.0)
            sims_top.append(sim_val)
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

        # Build summary lines
        summary_lines: List[str] = []

        anchor_titles = [str(a.get("title")).strip() for a in top_anchors if a.get("title")]
        if anchor_titles:
            if len(anchor_titles) == 1:
                summary_lines.append(f"Because you liked {anchor_titles[0]}.")
            elif len(anchor_titles) == 2:
                summary_lines.append(
                    f"Because you liked {anchor_titles[0]} and {anchor_titles[1]}."
                )
            else:
                summary_lines.append(
                    f"Because you liked {anchor_titles[0]}, {anchor_titles[1]} and {anchor_titles[2]}."
                )

        if shared_genres:
            if len(shared_genres) == 1:
                summary_lines.append(f"Shares a strong {shared_genres[0]} vibe.")
            else:
                top_g = ", ".join(shared_genres[:3])
                summary_lines.append(f"Shares genres like {top_g}.")

        if reddit_meta["count"] > 0:
            summary_lines.append(
                "These shows are often discussed together on Reddit, so they tend to appeal to similar audiences."
            )

        vote = target.get("vote_average")
        if isinstance(vote, (int, float)):
            if vote >= 8.5:
                summary_lines.append("Highly rated by other viewers.")
            elif vote >= 7.5:
                summary_lines.append("Well rated and liked by most audiences.")

        if not summary_lines:
            summary_lines.append(
                "This show overlaps strongly with your favourite shows in terms of tone and themes."
            )

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
        raise HTTPException(status_code=500, detail="Internal error in explanation engine")


@router.get("/smart-similar/{tmdb_id}")
async def get_smart_similar_for_show(
    tmdb_id: int,
    limit: int = Query(20, ge=1, le=50),
) -> Any:
    """
    Lightweight show-centric smart similar endpoint, used by the ShowDetails page.

    It does not depend on a particular user_id. Instead, it:
      - pulls TMDB recommendations for this tmdb_id
      - enriches them with basic TMDB details
      - returns up to `limit` items shaped like other recs_v3 results.
    """
    # Re-use the same API key resolution logic as _tmdb_details()
    api_key = (
        os.environ.get("TMDB_API_KEY")
        or os.environ.get("TMDB_KEY")
        or os.environ.get("TMDB_API")
    )
    if not api_key:
        # No TMDB key configured => just return empty list rather than 500
        return []

    try:
        # Use the helper that already pulls TMDB recommendations for a single favourite
        rec_ids = await _tmdb_recommendations_for_fav(tmdb_id, api_key, max_n=limit * 2)
        if not rec_ids:
            return []

        # Deduplicate while preserving order
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
            # _tmdb_details always returns a dict with "tmdb_id", and possibly title/name/poster.
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
        raise HTTPException(status_code=500, detail="Internal error in smart-similar")
