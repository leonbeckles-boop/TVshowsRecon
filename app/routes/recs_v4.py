from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.security import require_user_match

# v3 gives us the proven candidate sources and plumbing.
from app.routes.recs_v3 import (
    MIN_FAVORITES,
    _fetch_reddit_candidates_for_user,
    _fetch_reddit_candidates_from_pairs,
    _fetch_tmdb_candidates,
    _fetch_tmdb_trending_candidates,
    _fetch_user_favorites,
    _get_block_ids,
    _recent_first_bucket,
    _tmdb_details,
)

# SEO gives us the relevance/tone/quality judge.
from app.routes.seo import (
    ANCHOR_TO_CONCEPT,
    _anchor_profile,
    _bayesian_quality_score,
    _candidate_fit_adjustment,
    _classify_anchor_concept_v2,
    _concept_fit_score,
    _confidence_factor,
    _extract_anchor_keywords,
    _genre_overlap_score,
    _is_future_or_too_fresh_for_seo,
    _is_weak_scifi,
    _normalise_result_score,
    _passes_seo_quality_floor,
    _quality_bonus,
    _semantic_text_score,
    _source_label,
    passes_concept_guardrail,
)

try:
    from app.routes.seo import _blob_for
except Exception:
    def _blob_for(details: Dict[str, Any]) -> str:
        return " ".join(
            [
                str(details.get("title") or details.get("name") or ""),
                str(details.get("overview") or ""),
                " ".join([str(x) for x in (details.get("genres") or [])]),
            ]
        ).lower()


router = APIRouter(prefix="/recs/v4", tags=["recs_v4"])
log = logging.getLogger("recs_v4")

ENGINE = "v4_hybrid_v3_candidates_seo_rerank"

DEFAULT_LIMIT = 36
MAX_CANDIDATE_DETAILS = 260

BAD_FILLER_GENRES = {10764, 10767, 10766}  # Reality, Talk, Soap

LOW_VALUE_BROAD_TITLES = {
    "law & order",
    "law & order: special victims unit",
    "law & order: criminal intent",
    "law & order: organized crime",
    "midsomer murders",
    "all rise",
    "blue bloods",
    "the rookie",
    "fbi",
    "fbi: international",
    "fbi: most wanted",
    "ncis",
    "csi",
    "csi: crime scene investigation",
    "2 broke girls",
    "young sheldon",
    "chesapeake shores",
    "grey's anatomy",
}

GENERIC_PROCEDURAL_TERMS = (
    "special victims unit",
    "detectives who investigate",
    "elite squad",
    "nypd",
    "lapd",
    "fbi",
    "precinct",
    "case-of-the-week",
    "cases",
    "solve crimes",
    "solving crimes",
    "homicide unit",
    "police procedural",
    "murder mysteries",
    "each episode",
)

SOFT_COMFORT_TERMS = (
    "small town",
    "romance",
    "romantic",
    "family",
    "single mother",
    "community",
    "wedding",
    "marriage",
    "waitress",
    "diner",
    "roommates",
    "sitcom",
    "coming-of-age",
)

PRESTIGE_CRIME_TERMS = (
    "corruption",
    "cartel",
    "drug",
    "underworld",
    "organised crime",
    "organized crime",
    "moral",
    "political",
    "institution",
    "conspiracy",
    "gang",
    "mafia",
    "mob",
    "criminal empire",
    "antihero",
)

ANCHOR_CONCEPTS_CRIME_OK = {
    "crime_pressure",
    "detective_mystery",
    "small_town_mystery",
    "cartel_crime",
    "prestige_crime",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _title_of(details: Dict[str, Any]) -> str:
    return str(details.get("title") or details.get("name") or details.get("original_name") or "").strip()


def _genre_ids(details: Dict[str, Any]) -> Set[int]:
    out: Set[int] = set()
    for gid in details.get("genre_ids") or []:
        try:
            out.add(int(gid))
        except Exception:
            continue
    return out


def _contains_blob(details: Dict[str, Any], *terms: str) -> bool:
    blob = f"{_title_of(details).lower()} {str(details.get('overview') or '').lower()}"
    return any(t in blob for t in terms)


def _is_low_value_broad_candidate(details: Dict[str, Any]) -> bool:
    title = _title_of(details).lower()
    if title in LOW_VALUE_BROAD_TITLES:
        return True
    if any(title.startswith(prefix) for prefix in ("law & order", "csi", "ncis", "fbi")):
        return True
    return False


def _normalise_series(values: Dict[int, float]) -> Dict[int, float]:
    if not values:
        return {}
    max_v = max(values.values())
    if max_v <= 0:
        return {k: 0.0 for k in values}
    return {k: float(v) / max_v for k, v in values.items()}


def _cosine_genre_similarity(candidate_genres: Set[int], fav_genre_counts: Counter[int]) -> float:
    if not candidate_genres or not fav_genre_counts:
        return 0.0
    dot = sum(float(fav_genre_counts.get(g, 0)) for g in candidate_genres)
    cand_norm = math.sqrt(len(candidate_genres)) or 1.0
    fav_norm = math.sqrt(sum(float(c) * float(c) for c in fav_genre_counts.values())) or 1.0
    return max(0.0, min(1.0, dot / (cand_norm * fav_norm)))


def _candidate_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ga = _genre_ids(a)
    gb = _genre_ids(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb) or 1
    score = inter / union
    if inter == 1:
        score *= 0.65
    elif inter >= 3:
        score *= 1.08
    la = a.get("original_language")
    lb = b.get("original_language")
    if la and lb and la == lb:
        score += 0.06
    return max(0.0, min(1.0, score))


def _mmr(items: List[Dict[str, Any]], k: int, mmr_lambda: float) -> List[Dict[str, Any]]:
    if not items or k <= 0:
        return []
    remaining = list(items)
    selected: List[Dict[str, Any]] = []
    while remaining and len(selected) < k:
        best: Optional[Dict[str, Any]] = None
        best_score: Optional[float] = None
        for cand in remaining:
            rel = _safe_float(cand.get("score"))
            penalty = max((_candidate_similarity(cand, s) for s in selected), default=0.0)
            mmr_score = (mmr_lambda * rel) - ((1.0 - mmr_lambda) * penalty)
            if best_score is None or mmr_score > best_score:
                best_score = mmr_score
                best = cand
        if best is None:
            break
        selected.append(best)
        remaining = [x for x in remaining if _safe_int(x.get("tmdb_id")) != _safe_int(best.get("tmdb_id"))]
    return selected


def _is_obvious_anchor_mismatch(anchor_concept: str, details: Dict[str, Any]) -> bool:
    title = _title_of(details).lower()
    overview = str(details.get("overview") or "").lower()
    blob = f"{title} {overview}"
    genres = _genre_ids(details)

    def has(*terms: str) -> bool:
        return any(t in blob for t in terms)

    if anchor_concept == "finance_power":
        finance_signal = has(
            "finance", "hedge fund", "wall street", "billionaire", "wealth",
            "corporate", "business", "money", "executive", "ceo", "boardroom",
            "media empire", "conglomerate", "shareholder", "merger", "acquisition",
            "law firm", "attorney", "lawyer", "political", "power", "elite",
            "dynasty", "inheritance", "tycoon", "trading", "investment",
        )
        soft_family_signal = has(
            "small town", "single mother", "family", "romance", "romantic",
            "wedding", "marriage", "community", "chesapeake", "waitress",
            "diner", "roommates", "sitcom", "broke girls",
        ) or bool({35, 10751} & genres)
        if soft_family_signal and not finance_signal:
            return True
        if not finance_signal and 35 in genres:
            return True

    if anchor_concept in {"detective_mystery", "small_town_mystery"}:
        if has("possessed doll", "killer doll", "doll", "slasher", "supernatural", "teenage", "haunted"):
            return True
        if 35 in genres and not has("detective", "investigation", "murder", "police", "case"):
            return True

    if anchor_concept == "crime_pressure":
        if 35 in genres and not has("crime", "criminal", "gang", "cartel", "drug", "mafia", "mob", "heist"):
            return True

    return False

def _is_weak_anchor_category_match(
    *,
    title: str,
    anchor_title: str,
    anchor_concept: str,
    details: Dict[str, Any],
    anchor: Dict[str, Any],
    semantic_score: float,
    genre_score: float,
    concept_bonus: float,
) -> bool:
    title_l = title.lower()
    anchor_l = anchor_title.lower()
    genres = _genre_ids(details)
    anchor_genres = _genre_ids(anchor)

    is_comedy = 35 in genres
    anchor_is_comedy = 35 in anchor_genres
    is_crime = 80 in genres
    anchor_is_crime = 80 in anchor_genres
    is_family_or_soft = bool({10751, 10762} & genres) or _contains_blob(
        details,
        "family",
        "romance",
        "small town",
        "teen",
        "high school",
        "dating",
        "friendship",
    )

    # Block loose comedy/sitcom drift unless the matched favourite is also comedy-led.
    if is_comedy and not anchor_is_comedy:
        if semantic_score < 0.34 and concept_bonus < 0.20:
            return True

    # Block soft/teen/family dramas being justified by darker prestige anchors.
    if is_family_or_soft and anchor_concept not in {"medical_family", "period_community", "sitcom_comedy", "dark_comedy"}:
        if semantic_score < 0.32:
            return True

    # Block crime shows being justified by non-crime anchors unless the theme is very strong.
    if is_crime and not anchor_is_crime and anchor_concept not in ANCHOR_CONCEPTS_CRIME_OK:
        if semantic_score < 0.30 and concept_bonus < 0.18:
            return True

    # Known broad-title categories that are usually too generic for this profile.
    weak_broad_titles = {
        "sex and the city",
        "the o.c.",
        "grey's anatomy",
        "chesapeake shores",
        "2 broke girls",
        "young sheldon",
        "law & order: special victims unit",
        "midsomer murders",
        "all rise",
        "the marvelous mrs. maisel",
        "the newsroom",
        "rescue me",
    }
    if title_l in weak_broad_titles:
        return True

    # Specific recurring false-anchor patterns.
    if title_l in {"house", "house m.d."} and anchor_l == "sherlock":
        return True

    if title_l == "true blood" and anchor_l in {"pluribus", "black mirror", "severance"}:
        return True

    if title_l == "the diplomat" and anchor_l in {"the last kingdom", "game of thrones", "vikings"}:
        return True

    if title_l == "dexter: resurrection" and anchor_l == "only murders in the building":
        return True

    if title_l == "big little lies" and anchor_l in {"chernobyl", "the last of us", "sherlock"}:
        return True

    if title_l == "house of cards" and anchor_l == "the last of us":
        return True

    return False

def _pick_best_anchor(
    details: Dict[str, Any],
    fav_details: List[Dict[str, Any]],
    fav_genre_counts: Counter[int],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    best_anchor: Optional[Dict[str, Any]] = None
    best_payload: Dict[str, Any] = {
        "semantic": 0.0,
        "genre": 0.0,
        "profile_genre": 0.0,
        "fit_bonus": 0.0,
        "concept_bonus": 0.0,
        "concept_multiplier": 1.0,
        "concept": "general_drama",
    }
    best_total = -1.0

    cand_title = _title_of(details)
    cand_genres = _genre_ids(details)

    for anchor in fav_details:
        anchor_title = _title_of(anchor)
        if not anchor_title:
            continue

        anchor_genres = _genre_ids(anchor)
        anchor_keywords = _extract_anchor_keywords(
            anchor_title,
            anchor.get("overview"),
            " ".join([str(x) for x in (anchor.get("genres") or [])]),
        )
        anchor_profile = _anchor_profile(anchor)
        anchor_concept = ANCHOR_TO_CONCEPT.get(
            anchor_title.lower(),
            _classify_anchor_concept_v2(anchor_title, anchor),
        )

        semantic = _semantic_text_score(
            anchor_keywords,
            cand_title,
            details.get("overview"),
            " ".join([str(x) for x in (details.get("genres") or [])]),
        )
        genre = _genre_overlap_score(anchor_genres, cand_genres)

        fits_anchor, fit_bonus = _candidate_fit_adjustment(anchor_profile, details)
        if not fits_anchor:
            continue

        concept_pass, concept_bonus, concept_multiplier = _concept_fit_score(
            anchor_concept,
            details,
            semantic_score=semantic,
            genre_score=genre,
        )
        if not concept_pass:
            continue

        if anchor_concept and not passes_concept_guardrail(
            anchor_concept,
            _blob_for(details),
            list(details.get("genres") or []),
        ):
            continue

        if _is_obvious_anchor_mismatch(anchor_concept, details):
            continue

        # Specific-anchor gate. This is the critical difference from the old v4:
        # a show cannot pass just because it matches the user's broad genre cloud.
        if semantic < 0.10 and genre < 0.24 and concept_bonus < 0.10 and fit_bonus < 0.10:
            continue

        profile_genre = _cosine_genre_similarity(cand_genres, fav_genre_counts)
        total = (
            (0.62 * semantic)
            + (0.24 * genre)
            + (0.08 * profile_genre)
            + fit_bonus
            + concept_bonus
        )
        total *= concept_multiplier

        if total > best_total:
            best_total = total
            best_anchor = anchor
            best_payload = {
                "semantic": semantic,
                "genre": genre,
                "profile_genre": profile_genre,
                "fit_bonus": fit_bonus,
                "concept_bonus": concept_bonus,
                "concept_multiplier": concept_multiplier,
                "concept": anchor_concept,
            }

    return best_anchor, best_payload


def _merge_candidate_sources(*sources: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    by_id: Dict[int, Dict[str, Any]] = {}
    for source_items in sources:
        for item in source_items or []:
            tid = _safe_int(item.get("tmdb_id"))
            if not tid:
                continue
            source = str(item.get("source") or "unknown")
            raw = _safe_float(item.get("score_raw"), 1.0)
            entry = by_id.setdefault(
                tid,
                {
                    "tmdb_id": tid,
                    "scores_by_source": {},
                    "sources": set(),
                },
            )
            entry["scores_by_source"][source] = max(raw, _safe_float(entry["scores_by_source"].get(source)))
            entry["sources"].add(source)
    return by_id


def _source_strength_maps(by_id: Dict[int, Dict[str, Any]]) -> Tuple[Dict[int, float], Dict[int, float], Dict[int, float]]:
    reddit: Dict[int, float] = {}
    tmdb: Dict[int, float] = {}
    trending: Dict[int, float] = {}

    for tid, entry in by_id.items():
        scores = entry.get("scores_by_source") or {}
        reddit[tid] = max(
            _safe_float(scores.get("reddit_pairs")),
            _safe_float(scores.get("user_reddit_pairs")),
        )
        tmdb[tid] = _safe_float(scores.get("tmdb_recs"))
        trending[tid] = _safe_float(scores.get("tmdb_trending"))

    return (
        _normalise_series(reddit),
        _normalise_series(tmdb),
        _normalise_series(trending),
    )


def _reason_lines(
    anchor_title: str,
    shared_genres: List[str],
    semantic_score: float,
    source: str,
) -> List[str]:
    lines: List[str] = []
    if anchor_title:
        if semantic_score >= 0.24:
            lines.append(f"Strong tonal match with {anchor_title}.")
        else:
            lines.append(f"Shares some of the same appeal as {anchor_title}.")
    if shared_genres:
        lines.append("Shared genres: " + ", ".join(shared_genres[:3]) + ".")
    if source in {"multi_signal", "reddit_pairs"}:
        lines.append("Also supported by audience co-mention signals.")
    elif source == "tmdb_recs":
        lines.append("Also surfaced by TMDB recommendation signals.")
    elif source == "semantic_match":
        lines.append("Picked mainly for theme, tone and story fit.")
    return lines[:3]


@router.get("/diag-ez")
async def diag_ez() -> Dict[str, Any]:
    return {"ok": True, "who": "recs_v4", "engine": ENGINE}


@router.get("/{user_id}")
async def get_recs_v4(
    user_id: int,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=200),
    # Hybrid scoring: SEO fit dominates. Source strength can only boost candidates that already passed fit gates.
    w_fit: float = Query(0.58, ge=0.0, le=1.0),
    w_source: float = Query(0.17, ge=0.0, le=1.0),
    w_quality: float = Query(0.17, ge=0.0, le=1.0),
    w_freshness: float = Query(0.04, ge=0.0, le=0.25),
    mmr_lambda: float = Query(0.74, ge=0.0, le=1.0),
    flat: int = Query(0),
    recent_first: int = Query(0),
    recent_years: int = Query(3, ge=1, le=20),
    debug: int = Query(0),
    _: Any = Depends(require_user_match),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """
    v4 hybrid recommendations.

    Architecture:
      1. Gather v3-style candidates from Reddit/TMDB/trending.
      2. Score every candidate against every favourite using SEO-style fit.
      3. Reject anything without a strong specific anchor.
      4. Use Reddit/TMDB as boosts only after the fit gate passes.
    """
    try:
        block_ids = await _get_block_ids(session, user_id)
        fav_ids = await _fetch_user_favorites(session, user_id)

        if len(fav_ids) < MIN_FAVORITES:
            payload = {
                "items": [],
                "meta": {
                    "user_id": user_id,
                    "version": "v4",
                    "engine": ENGINE,
                    "n_candidates": 0,
                    "n_favorites": len(fav_ids),
                    "min_favorites": MIN_FAVORITES,
                    "reason": "not_enough_favorites",
                },
            }
            return [] if flat else payload

        fav_details_raw = await asyncio.gather(*[_tmdb_details(fid) for fid in fav_ids], return_exceptions=True)
        fav_details = [d for d in fav_details_raw if isinstance(d, dict) and _title_of(d)]

        fav_genre_counts: Counter[int] = Counter()
        for fav in fav_details:
            fav_genre_counts.update(_genre_ids(fav))

        allowed_langs = {
            str(d.get("original_language"))
            for d in fav_details
            if d.get("original_language")
        }
        fav_genres_all = set(fav_genre_counts.keys())

        # Candidate generation is deliberately v3-style.
        candidate_limit = max(limit * 5, 90)

        reddit_base = await _fetch_reddit_candidates_for_user(session, user_id, candidate_limit, block_ids)
        if not reddit_base:
            reddit_base = await _fetch_reddit_candidates_from_pairs(session, fav_ids, candidate_limit, block_ids)

        tmdb_base = await _fetch_tmdb_candidates(fav_ids, block_ids, candidate_limit)

        trending_base = await _fetch_tmdb_trending_candidates(
            allowed_langs=allowed_langs,
            fav_genres=fav_genres_all,
            block_ids=block_ids,
            limit=max(limit * 2, 48),
        )
        trending_base = trending_base[: min(max(12, int(limit * 0.75)), 48)]

        by_id = _merge_candidate_sources(reddit_base, tmdb_base, trending_base)
        if not by_id:
            payload = {
                "items": [],
                "meta": {
                    "user_id": user_id,
                    "version": "v4",
                    "engine": ENGINE,
                    "n_candidates": 0,
                    "n_favorites": len(fav_ids),
                    "reason": "no_candidates",
                },
            }
            return [] if flat else payload

        reddit_strength, tmdb_strength, trending_strength = _source_strength_maps(by_id)

        candidate_ids = list(by_id.keys())[:MAX_CANDIDATE_DETAILS]
        details_raw = await asyncio.gather(*[_tmdb_details(tid) for tid in candidate_ids], return_exceptions=True)
        details_list = [d for d in details_raw if isinstance(d, dict) and _safe_int(d.get("tmdb_id"))]

        scored: List[Dict[str, Any]] = []
        now_year = datetime.now(timezone.utc).year

        for details in details_list:
            tid = _safe_int(details.get("tmdb_id"))
            if not tid or tid in block_ids:
                continue

            title = _title_of(details)
            if not title:
                continue

            genres = _genre_ids(details)
            if genres & BAD_FILLER_GENRES:
                continue

            if _is_low_value_broad_candidate(details):
                continue

            vote_average = _safe_float(details.get("vote_average"))
            vote_count = _safe_int(details.get("vote_count"))
            popularity = _safe_float(details.get("popularity"))
            first_air_date = str(details.get("first_air_date") or "")

            if _is_future_or_too_fresh_for_seo(first_air_date, vote_count):
                continue

            anchor, fit = _pick_best_anchor(details, fav_details, fav_genre_counts)
            if not anchor:
                continue

            anchor_title = _title_of(anchor)
            anchor_concept = str(fit.get("concept") or "general_drama")
            semantic_score = _safe_float(fit.get("semantic"))
            genre_score = _safe_float(fit.get("genre"))
            profile_genre = _safe_float(fit.get("profile_genre"))
            concept_bonus = _safe_float(fit.get("concept_bonus"))
            fit_bonus = _safe_float(fit.get("fit_bonus"))
            concept_multiplier = _safe_float(fit.get("concept_multiplier"), 1.0)
            anchor_genres = _genre_ids(anchor)

            # Hard broad-profile guardrails.
            if _contains_blob(details, *SOFT_COMFORT_TERMS) and anchor_concept not in {"medical_family", "period_community"}:
                if 35 in genres or 10751 in genres or semantic_score < 0.30:
                    continue

            if _contains_blob(details, *GENERIC_PROCEDURAL_TERMS):
                if not _contains_blob(details, *PRESTIGE_CRIME_TERMS):
                    continue

            if 35 in genres and 35 not in anchor_genres and semantic_score < 0.30 and concept_bonus < 0.18:
                continue

            # Block loose sitcom/comedy matches unless the matched favourite is also comedy-led.
            # This stops things like The Office being justified by Severance.
            if 35 in genres and 35 not in anchor_genres:
                comedy_anchor_concepts = {"sitcom_comedy", "dark_comedy", "workplace_comedy", "animated_comedy"}
                if anchor_concept not in comedy_anchor_concepts:
                    continue

            if anchor_concept not in ANCHOR_CONCEPTS_CRIME_OK and 80 in genres:
                if not _contains_blob(details, *PRESTIGE_CRIME_TERMS) and semantic_score < 0.26:
                    continue

            if 10765 in _genre_ids(anchor) and _is_weak_scifi(details) and semantic_score < 0.22 and concept_bonus < 0.16:
                continue

            if _is_obvious_anchor_mismatch(anchor_concept, details):
                continue

            if _is_weak_anchor_category_match(
                title=title,
                anchor_title=anchor_title,
                anchor_concept=anchor_concept,
                details=details,
                anchor=anchor,
                semantic_score=semantic_score,
                genre_score=genre_score,
                concept_bonus=concept_bonus,
            ):
                continue

            # Core fit gate: source signals cannot rescue a weak match.
            anchor_fit_score = (
                (0.52 * semantic_score)
                + (0.24 * genre_score)
                + (0.08 * profile_genre)
                + min(0.20, concept_bonus)
                + min(0.14, fit_bonus)
            ) * concept_multiplier

            if anchor_fit_score < 0.30:
                continue

            if semantic_score < 0.14 and genre_score < 0.28 and concept_bonus < 0.14 and fit_bonus < 0.14:
                continue

            is_reddit = reddit_strength.get(tid, 0.0) > 0
            is_tmdb = tmdb_strength.get(tid, 0.0) > 0
            is_trending = trending_strength.get(tid, 0.0) > 0

            if not _passes_seo_quality_floor(
                vote_average=vote_average,
                vote_count=vote_count,
                popularity=popularity,
                semantic_score=semantic_score + min(0.18, concept_bonus),
                genre_score=max(genre_score, profile_genre * 0.65),
                is_reddit=is_reddit,
                is_tmdb=is_tmdb,
                is_trending=is_trending,
            ):
                continue

            bayes_quality = _bayesian_quality_score(vote_average, vote_count)
            qual_bonus = _quality_bonus(vote_average, vote_count, popularity)
            conf_factor = _confidence_factor(vote_count, popularity)

            # Source score: boosts only after gates are passed.
            source_score = 0.0
            source_score += 0.48 * reddit_strength.get(tid, 0.0)
            source_score += 0.36 * tmdb_strength.get(tid, 0.0)
            source_score += 0.16 * trending_strength.get(tid, 0.0)
            source_score = min(1.0, source_score)

            freshness = 0.0
            if first_air_date and len(first_air_date) >= 4:
                year = _safe_int(first_air_date[:4])
                if year:
                    age = max(0, now_year - year)
                    freshness = math.exp(-age / 5.5)

            score = 0.0
            score += w_fit * anchor_fit_score
            score += w_source * source_score
            score += w_quality * (bayes_quality + min(0.10, qual_bonus))
            score += w_freshness * freshness
            score *= conf_factor

            # Single-source candidates need to be better than multi-signal candidates.
            if is_reddit and not is_tmdb and not is_trending and anchor_fit_score < 0.48:
                continue
            if is_tmdb and not is_reddit and not is_trending and anchor_fit_score < 0.36:
                continue

            min_score = 0.42
            if anchor_concept in {"medical_family", "period_community"}:
                min_score = 0.34
            if score < min_score:
                continue

            source = _source_label(is_reddit, is_tmdb, is_trending, semantic_score)
            if source == "semantic_fallback":
                source = "semantic_match"
            if sum([is_reddit, is_tmdb, is_trending]) >= 2:
                source = "multi_signal"

            anchor_genre_names = {str(x).strip() for x in anchor.get("genres") or [] if str(x).strip()}
            cand_genre_names = {str(x).strip() for x in details.get("genres") or [] if str(x).strip()}
            shared_genres = sorted(anchor_genire_names & cand_genre_names) if False else sorted(anchor_genre_names & cand_genre_names)

            item = {
                "tmdb_id": tid,
                "title": title,
                "name": title,
                "poster_path": details.get("poster_path"),
                "poster_url": details.get("poster_url"),
                "overview": details.get("overview"),
                "first_air_date": details.get("first_air_date"),
                "origin_country": details.get("origin_country"),
                "original_language": details.get("original_language"),
                "vote_average": vote_average,
                "vote_count": vote_count,
                "popularity": popularity,
                "genres": details.get("genres") or [],
                "genre_ids": details.get("genre_ids") or [],
                "source": source,
                "score": float(score),
                "anchor_favorite": {
                    "tmdb_id": _safe_int(anchor.get("tmdb_id")),
                    "title": anchor_title,
                },
                "reason": _reason_lines(anchor_title, shared_genres, semantic_score, source),
                "debug": {
                    "engine": ENGINE,
                    "anchor_fit_score": anchor_fit_score,
                    "semantic": semantic_score,
                    "genre": genre_score,
                    "profile_genre": profile_genre,
                    "quality": bayes_quality,
                    "source_score": source_score,
                    "reddit": reddit_strength.get(tid, 0.0),
                    "tmdb": tmdb_strength.get(tid, 0.0),
                    "trending": trending_strength.get(tid, 0.0),
                    "freshness": freshness,
                    "concept": anchor_concept,
                    "concept_bonus": concept_bonus,
                    "fit_bonus": fit_bonus,
                },
            }
            scored.append(_normalise_result_score(item))

        scored.sort(
            key=lambda x: (
                _safe_float(x.get("score")),
                _safe_float(x.get("vote_average")),
                _safe_float(x.get("popularity")),
            ),
            reverse=True,
        )

        diversified = _mmr(scored, limit, mmr_lambda)
        if recent_first:
            diversified = _recent_first_bucket(diversified, years=recent_years)

        if not debug:
            for item in diversified:
                item.pop("debug", None)

        if flat:
            return diversified

        return {
            "items": diversified,
            "meta": {
                "user_id": user_id,
                "version": "v4",
                "engine": ENGINE,
                "n_candidates": len(by_id),
                "n_scored": len(scored),
                "n_returned": len(diversified),
                "n_favorites": len(fav_ids),
                "weights": {
                    "w_fit": w_fit,
                    "w_source": w_source,
                    "w_quality": w_quality,
                    "w_freshness": w_freshness,
                },
                "mmr_lambda": mmr_lambda,
                "candidate_sources": {
                    "reddit": len(reddit_base),
                    "tmdb": len(tmdb_base),
                    "trending": len(trending_base),
                },
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("recs_v4 failed")
        raise HTTPException(status_code=500, detail=f"recs_v4 failed: {exc}")
