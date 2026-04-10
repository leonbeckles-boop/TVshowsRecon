from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.routes.recs_v3 import (
    _tmdb_api_key,
    _tmdb_details,
    _tmdb_recommendations_for_fav,
    _fetch_tmdb_trending_candidates,
)

import asyncio
import math
import re
from collections import Counter

router = APIRouter(prefix="/api/seo", tags=["seo"])

MIN_RESULTS = 12
MAX_RESULTS = 24

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "their",
    "they", "them", "have", "has", "had", "was", "were", "are", "but",
    "about", "after", "before", "over", "under", "when", "while", "where",
    "what", "who", "why", "how", "you", "your", "our", "his", "her", "its",
    "she", "him", "his", "hers", "than", "then", "out", "off", "too", "very",
    "series", "show", "story", "stories", "season", "seasons", "episode",
    "episodes", "drama", "comedy", "family", "kids", "reality", "television",
    "life", "new", "old", "young", "set", "one", "two", "three", "four",
    "five", "their", "often", "next", "people", "watch", "watching", "viewer",
    "viewers", "about", "through", "across", "around", "within", "without",
    "love", "like", "more", "most", "some", "many", "each", "other",
}

BAD_GENRES = {
    10751,  # Family
    10762,  # Kids
    10764,  # Reality
}


def _tokenise(text_val: str | None) -> list[str]:
    if not text_val:
        return []
    words = re.findall(r"[a-zA-Z]{3,}", text_val.lower())
    return [w for w in words if w not in STOPWORDS]


def _extract_anchor_keywords(*parts: str | None, top_n: int = 14) -> list[str]:
    counts: Counter[str] = Counter()
    for part in parts:
        counts.update(_tokenise(part))
    boosts = {
        "spy": 3, "spies": 3, "espionage": 4, "cia": 4, "kgb": 4, "agent": 2,
        "agents": 2, "undercover": 3, "intelligence": 3, "mystery": 2,
        "crime": 2, "thriller": 2, "murder": 2, "political": 2, "war": 2,
        "survival": 2, "dystopian": 3, "time": 1, "travel": 1, "sci": 1,
        "period": 3, "historical": 3, "victorian": 3, "midwife": 5,
        "nurse": 4, "nurses": 4, "medical": 4, "hospital": 4, "doctor": 3,
        "family": 3, "community": 3, "romance": 2, "british": 2,
        "bbc": 2, "england": 2, "london": 2, "small": 1, "town": 1,
        "marriage": 2, "mother": 2, "women": 2, "gentle": 1, "warm": 1,
    }
    for token, boost in boosts.items():
        if token in counts:
            counts[token] += boost
    return [w for w, _ in counts.most_common(top_n)]


def _semantic_text_score(anchor_keywords: list[str], *candidate_parts: str | None) -> float:
    if not anchor_keywords:
        return 0.0
    candidate_tokens = set()
    for part in candidate_parts:
        candidate_tokens.update(_tokenise(part))
    if not candidate_tokens:
        return 0.0

    overlap = 0.0
    for kw in anchor_keywords:
        if kw in candidate_tokens:
            overlap += 1.0

    score = overlap / max(1.0, len(anchor_keywords))
    joined = " ".join(candidate_tokens)
    if any(k in joined for k in ("spy", "espionage", "cia", "kgb", "undercover", "agent", "intelligence")):
        score += 0.08
    if any(k in joined for k in ("crime", "thriller", "mystery", "murder", "political")):
        score += 0.04
    if any(k in joined for k in ("period", "historical", "medical", "hospital", "nurse", "family", "community", "romance")):
        score += 0.05
    if any(k in joined for k in ("british", "bbc", "england", "london", "midwife", "village", "marriage")):
        score += 0.04

    return float(min(score, 1.0))


def _genre_overlap_score(anchor_genre_ids: set[int], candidate_genre_ids: set[int]) -> float:
    if not anchor_genre_ids or not candidate_genre_ids:
        return 0.0
    overlap = len(anchor_genre_ids & candidate_genre_ids)
    union = len(anchor_genre_ids | candidate_genre_ids) or 1
    base = overlap / union
    if overlap >= 2:
        base += 0.10
    return float(min(base, 1.0))


def _quality_bonus(vote_average: float, vote_count: int) -> float:
    if vote_average >= 8.0 and vote_count >= 150:
        return 0.22
    if vote_average >= 7.5 and vote_count >= 100:
        return 0.15
    if vote_average >= 7.0 and vote_count >= 50:
        return 0.08
    return 0.0


def _natural_join(items: list[str]) -> str:
    vals = [str(x).strip() for x in items if str(x).strip()]
    if not vals:
        return ""
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 2:
        return f"{vals[0]} and {vals[1]}"
    return f"{', '.join(vals[:-1])}, and {vals[-1]}"


def _top_titles(results: list[dict], max_n: int = 3) -> list[str]:
    out: list[str] = []
    for item in results[:max_n]:
        title = str(item.get("title") or "").strip()
        if title:
            out.append(title)
    return out


def _top_genres(results: list[dict], max_n: int = 2) -> list[str]:
    counts: Counter[str] = Counter()
    for item in results:
        genres = item.get("genres") or []
        if not isinstance(genres, list):
            continue
        for g in genres:
            name = str(g or "").strip()
            if name:
                counts[name] += 1
    return [name for name, _ in counts.most_common(max_n)]


def _genre_name_set(details: dict) -> set[str]:
    vals = set()
    for g in details.get("genres") or []:
        name = str(g or "").strip().lower()
        if name:
            vals.add(name)
    return vals


def _country_fit_bonus(anchor_details: dict, details: dict) -> float:
    anchor_blob = " ".join(
        [
            str(anchor_details.get("title") or anchor_details.get("name") or ""),
            str(anchor_details.get("overview") or ""),
            " ".join(anchor_details.get("genres") or []),
            " ".join(anchor_details.get("origin_country") or []),
        ]
    ).lower()
    cand_blob = " ".join(
        [
            str(details.get("title") or details.get("name") or ""),
            str(details.get("overview") or ""),
            " ".join(details.get("genres") or []),
            " ".join(details.get("origin_country") or []),
        ]
    ).lower()

    bonus = 0.0
    anchor_is_britishish = any(t in anchor_blob for t in ("british", "bbc", "england", "london", "uk", "gb"))
    cand_is_britishish = any(t in cand_blob for t in ("british", "bbc", "england", "london", "uk", "gb")) or "gb" in [
        str(x).lower() for x in (details.get("origin_country") or [])
    ]

    if anchor_is_britishish and cand_is_britishish:
        bonus += 0.08

    return bonus


def _anchor_profile(anchor_details: dict) -> dict[str, bool]:
    genre_names = _genre_name_set(anchor_details)
    text_blob = " ".join(
        [
            str(anchor_details.get("title") or anchor_details.get("name") or ""),
            str(anchor_details.get("overview") or ""),
            " ".join(anchor_details.get("genres") or []),
            " ".join(anchor_details.get("origin_country") or []),
        ]
    ).lower()

    has = lambda *terms: any(t in text_blob for t in terms)

    is_actionish = bool(
        {"action & adventure", "crime", "sci-fi & fantasy", "animation"} & genre_names
    )
    is_grounded_drama = "drama" in genre_names and not is_actionish
    is_period = (
        "war & politics" in genre_names
        or has("period", "historical", "victorian", "georgian", "post-war", "postwar", "1950", "1960", "1940", "18th", "19th")
    )
    is_medical_family = has("midwife", "nurse", "nurses", "hospital", "medical", "doctor", "maternity") or (
        is_grounded_drama and has("family", "community", "mother", "women", "village")
    )
    prefers_romance_family = is_period or has("romance", "family", "community", "village", "marriage", "courtship")
    is_britishish = has("british", "bbc", "england", "london", "uk") or "gb" in [
        str(x).lower() for x in (anchor_details.get("origin_country") or [])
    ]
    is_gentle_grounded = is_grounded_drama and has(
        "community", "family", "village", "mother", "women", "marriage", "midwife", "nurse", "hospital"
    )
    avoids_action_crime = is_grounded_drama and not has("crime", "murder", "detective", "police", "gang", "spy", "espionage")
    avoids_speculative = is_grounded_drama and not has("supernatural", "fantasy", "alien", "future", "post-apocalyptic", "superhero", "time travel")

    return {
        "grounded_drama": is_grounded_drama,
        "period": is_period,
        "medical_family": is_medical_family,
        "prefers_romance_family": prefers_romance_family,
        "avoids_action_crime": avoids_action_crime,
        "avoids_speculative": avoids_speculative,
        "britishish": is_britishish,
        "gentle_grounded": is_gentle_grounded,
    }


def _candidate_fit_adjustment(anchor_profile: dict[str, bool], details: dict) -> tuple[bool, float]:
    genre_names = _genre_name_set(details)
    text_blob = " ".join(
        [
            str(details.get("title") or details.get("name") or ""),
            str(details.get("overview") or ""),
            " ".join(details.get("genres") or []),
            " ".join(details.get("origin_country") or []),
        ]
    ).lower()

    has = lambda *terms: any(t in text_blob for t in terms)

    bonus = 0.0

    is_action = "action & adventure" in genre_names
    is_crime = "crime" in genre_names
    is_speculative = bool({"sci-fi & fantasy", "animation"} & genre_names) or has(
        "superhero", "vigilante", "marvel", "comic", "alien", "fantasy", "supernatural", "post-apocalyptic", "time travel", "parallel universe"
    )
    is_period = "war & politics" in genre_names or has(
        "period", "historical", "victorian", "georgian", "18th", "19th", "1940", "1950", "1960"
    )
    is_medical = has("midwife", "nurse", "nurses", "hospital", "medical", "doctor", "ward", "clinic")
    is_family_community = has("family", "community", "village", "small town", "mother", "marriage") or "family" in genre_names
    is_romance = has("romance", "romantic", "love", "marriage", "courtship")
    is_comedy_heavy = "comedy" in genre_names and "drama" not in genre_names
    is_documentary = 99 in set(details.get("genre_ids") or [])
    is_britishish = has("british", "bbc", "england", "london", "uk") or "gb" in [
        str(x).lower() for x in (details.get("origin_country") or [])
    ]

    if is_documentary:
        return False, 0.0

    if anchor_profile["avoids_speculative"] and is_speculative:
        return False, 0.0

    if anchor_profile["avoids_action_crime"] and (is_action or is_crime):
        if not (is_period or is_medical or is_family_community):
            return False, 0.0

    if anchor_profile["gentle_grounded"] and is_comedy_heavy:
        return False, 0.0

    if anchor_profile["period"]:
        if is_period:
            bonus += 0.20
        elif not (is_medical or is_family_community or is_romance):
            return False, 0.0

    if anchor_profile["medical_family"]:
        if is_medical:
            bonus += 0.20
        elif is_family_community:
            bonus += 0.12
        elif not (is_period or is_romance):
            return False, 0.0

    if anchor_profile["prefers_romance_family"]:
        if is_family_community:
            bonus += 0.08
        if is_romance:
            bonus += 0.06

    if anchor_profile["britishish"] and is_britishish:
        bonus += 0.08

    if anchor_profile["grounded_drama"] and "drama" in genre_names:
        bonus += 0.05

    return True, bonus


def _build_page_copy(anchor_title: str, results: list[dict]) -> dict:
    titles = _top_titles(results, 3)
    top_titles_text = _natural_join(titles)

    genres = _top_genres(results, 2)
    genre_text = ""
    if len(genres) == 1:
        genre_text = genres[0].lower()
    elif len(genres) >= 2:
        genre_text = f"{genres[0].lower()} and {genres[1].lower()}"

    sources = {str(r.get("source") or "").strip() for r in results}
    has_reddit = "reddit_pairs" in sources or "multi_signal" in sources
    has_tmdb = "tmdb_recs" in sources or "multi_signal" in sources
    has_semantic = "semantic_fallback" in sources

    intro = f"Looking for shows like {anchor_title}? These recommendations highlight series that viewers often move to next after finishing it."
    seo_blurb = f"If you enjoyed {anchor_title}, these recommendations point you toward similar TV series with overlapping tone, storytelling style and audience appeal."

    if genre_text and has_reddit and has_tmdb:
        intro = (
            f"Looking for shows like {anchor_title}? This list focuses on {genre_text} series "
            f"that line up well with {anchor_title}, combining audience viewing patterns with closely related recommendation signals."
        )
    elif genre_text and has_reddit:
        intro = (
            f"Looking for shows like {anchor_title}? These picks lean into the {genre_text} "
            f"elements that often connect with fans of {anchor_title}."
        )
    elif genre_text and has_semantic:
        intro = (
            f"Looking for shows like {anchor_title}? These recommendations were chosen for their shared "
            f"{genre_text} appeal, with a similar tone, style or storytelling feel."
        )
    elif top_titles_text:
        intro = (
            f"Looking for shows like {anchor_title}? Start with {top_titles_text} — they’re among the "
            f"strongest next-watch options for fans of {anchor_title}."
        )

    if top_titles_text and genre_text:
        seo_blurb = (
            f"If you enjoyed {anchor_title}, you may also like {top_titles_text}. These recommendations "
            f"reflect the kind of {genre_text} storytelling that often appeals to viewers looking for "
            f"something with a similar feel."
        )
    elif top_titles_text:
        seo_blurb = (
            f"If you enjoyed {anchor_title}, you may also like {top_titles_text}. These shows were "
            f"selected because they offer a similar viewing experience for fans looking for what to watch next."
        )

    faq_items = [
        {
            "question": f"Why do people who like {anchor_title} enjoy these shows?",
            "answer": (
                f"{anchor_title} tends to appeal to viewers who enjoy strong tone, memorable characters and a story "
                f"that keeps building over time. Shows like {top_titles_text} offer a similar kind of pull, even when "
                f"they take that idea in slightly different directions."
                if top_titles_text
                else f"{anchor_title} tends to attract viewers who enjoy strong storytelling, distinctive tone and character-led plots."
            ),
        },
        {
            "question": f"What should I watch after {anchor_title}?",
            "answer": (
                f"A good next watch after {anchor_title} depends on what you liked most about it. {top_titles_text} are "
                f"all strong follow-up options, whether you were drawn in by the atmosphere, the characters or the pacing."
                if top_titles_text
                else f"Your next watch after {anchor_title} really depends on whether you liked its tone, pacing or character work most."
            ),
        },
        {
            "question": f"What kind of shows are usually recommended to fans of {anchor_title}?",
            "answer": (
                f"Fans of {anchor_title} are often recommended {genre_text} series with a similar balance of tension, "
                f"character focus and story momentum rather than shows that only match on genre alone."
                if genre_text
                else f"Fans of {anchor_title} are often recommended character-driven series with a similar balance of tension, pacing and story momentum."
            ),
        },
        {
            "question": f"Where can I discover more shows like {anchor_title}?",
            "answer": (
                f"WhatNext helps you discover more shows based on your taste. Save favourites, build a watchlist and rate "
                f"what you’ve seen to keep improving your recommendations over time."
            ),
        },
    ]

    return {
        "intro": intro,
        "seo_blurb": seo_blurb,
        "top_titles_text": top_titles_text,
        "top_genres": genres,
        "faq_items": faq_items,
    }


@router.get("/shows-like/{slug}")
async def shows_like(
    slug: str,
    db: AsyncSession = Depends(get_async_session),
):
    title = slug.replace("-", " ")

    show_res = await db.execute(
        text(
            """
            SELECT
                show_id,
                title,
                poster_path
            FROM shows
            WHERE lower(title) = lower(:title)
            LIMIT 1
            """
        ),
        {"title": title},
    )

    row = show_res.mappings().first()

    if not row:
        from app.routes.recs_v3 import _tmdb_search_tv

        tmdb_match = await _tmdb_search_tv(title)
        if not tmdb_match:
            raise HTTPException(status_code=404, detail="Show not found")

        tmdb_id = tmdb_match.get("id")
        if not isinstance(tmdb_id, int):
            raise HTTPException(status_code=404, detail="Show not found")

        details = await _tmdb_details(tmdb_id)

        row = {
            "show_id": tmdb_id,
            "title": details.get("title") or details.get("name") or title.title(),
            "poster_path": details.get("poster_path"),
        }

    tmdb_id = int(row["show_id"])
    print("SEO anchor:", row["title"], tmdb_id)

    anchor_details = await _tmdb_details(tmdb_id)
    anchor_genre_ids = set(anchor_details.get("genre_ids") or [])
    anchor_lang = anchor_details.get("original_language")
    anchor_keywords = _extract_anchor_keywords(
        anchor_details.get("title") or anchor_details.get("name"),
        anchor_details.get("overview"),
        " ".join(anchor_details.get("genres") or []),
    )
    anchor_profile = _anchor_profile(anchor_details)

    api_key = _tmdb_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="TMDB API key not configured")

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
            res = await db.execute(reddit_sql, {"tid": tmdb_id, "lim": MAX_RESULTS * 3})
            rows = res.mappings().all()
            out = {}
            for r in rows:
                other_id = r.get("other_id")
                if other_id is None:
                    continue
                try:
                    oid = int(other_id)
                    pw = float(r.get("pair_weight") or 0.0)
                except Exception:
                    continue
                out[oid] = max(out.get(oid, 0.0), pw)
            return out
        except Exception:
            return {}

    tmdb_task = _tmdb_recommendations_for_fav(tmdb_id, api_key, max_n=MAX_RESULTS * 3)
    trending_task = _fetch_tmdb_trending_candidates(
        allowed_langs={anchor_lang} if anchor_lang else set(),
        fav_genres=anchor_genre_ids,
        block_ids={tmdb_id},
        limit=MAX_RESULTS * 2,
    )

    tmdb_ids_raw, reddit_scores, trending_items = await asyncio.gather(
        tmdb_task,
        _fetch_reddit_similar(),
        trending_task,
    )

    trending_scores: dict[int, float] = {}
    for item in (trending_items or []):
        try:
            rid = int(item.get("tmdb_id") or 0)
            raw = float(item.get("score_raw") or 0.0)
        except Exception:
            continue
        if rid and rid != tmdb_id:
            trending_scores[rid] = max(trending_scores.get(rid, 0.0), raw)

    merged_scores: dict[int, float] = {}

    for rid in (tmdb_ids_raw or []):
        if not isinstance(rid, int) or rid == tmdb_id:
            continue
        merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.18

    for rid, raw in trending_scores.items():
        merged_scores[rid] = merged_scores.get(rid, 0.0) + min(0.10, 0.04 + 0.07 * raw)

    for rid, pw in (reddit_scores or {}).items():
        if rid == tmdb_id:
            continue
        reddit_score = 1.15 * math.log10(1.0 + max(pw, 0.0))
        merged_scores[rid] = merged_scores.get(rid, 0.0) + reddit_score

    sorted_ids = sorted(merged_scores.keys(), key=lambda x: merged_scores[x], reverse=True)
    fetch_ids = sorted_ids[: MAX_RESULTS * 4]
    details_list = await asyncio.gather(*[_tmdb_details(rid) for rid in fetch_ids])

    results: list[dict] = []
    seen_ids = {tmdb_id}
    tmdb_set = set(tmdb_ids_raw or [])
    reddit_set = set(reddit_scores.keys())
    trending_set = set(trending_scores.keys())

    for details in details_list:
        try:
            rid = int(details.get("tmdb_id") or 0)
        except Exception:
            rid = 0

        if not rid or rid in seen_ids:
            continue

        title_val = details.get("title") or details.get("name")
        if not title_val:
            continue

        poster_path = details.get("poster_path")
        if not poster_path:
            continue

        genre_ids = set(details.get("genre_ids") or [])
        genre_names = _genre_name_set(details)

        if genre_ids & BAD_GENRES:
            continue
        if 10767 in genre_ids or 10766 in genre_ids:
            continue
        if 99 in genre_ids and len(genre_ids) == 1:
            continue

        vote_count = int(details.get("vote_count") or 0)
        vote_average = float(details.get("vote_average") or 0.0)

        if vote_count < 20 and vote_average < 6.5:
            continue

        genre_score = _genre_overlap_score(anchor_genre_ids, genre_ids)
        semantic_score = _semantic_text_score(
            anchor_keywords,
            details.get("title") or details.get("name"),
            details.get("overview"),
            " ".join(details.get("genres") or []),
        )
        qual_bonus = _quality_bonus(vote_average, vote_count)

        is_tmdb = rid in tmdb_set
        is_reddit = rid in reddit_set
        is_trending = rid in trending_set

        fits_anchor, fit_bonus = _candidate_fit_adjustment(anchor_profile, details)
        if not fits_anchor:
            continue

        total_score = float(merged_scores.get(rid, 0.0))
        total_score += 0.65 * semantic_score
        total_score += 0.35 * genre_score
        total_score += qual_bonus
        total_score += fit_bonus
        total_score += _country_fit_bonus(anchor_details, details)

        if anchor_profile["grounded_drama"]:
            if "drama" not in genre_names and semantic_score < 0.22:
                continue

        if anchor_profile["period"] and genre_score == 0.0 and semantic_score < 0.22 and fit_bonus < 0.18:
            continue

        if anchor_profile["medical_family"] and semantic_score < 0.10 and fit_bonus < 0.12:
            continue

        if anchor_profile["gentle_grounded"] and (is_tmdb or is_trending):
            if genre_score < 0.12 and semantic_score < 0.16:
                continue

        if is_tmdb and not is_reddit:
            if genre_score < 0.12 and semantic_score < 0.14:
                continue
            if genre_score == 0.0 and vote_average < 7.3:
                continue

        if not is_reddit and genre_score < 0.10 and semantic_score < 0.12:
            continue

        if is_tmdb and not is_reddit:
            total_score *= 0.68

        if is_trending and not is_reddit and semantic_score >= 0.18:
            total_score += 0.04

        if total_score < 0.28:
            continue

        seen_ids.add(rid)

        source = (
            "multi_signal"
            if is_reddit and (is_tmdb or is_trending)
            else "reddit_pairs"
            if is_reddit
            else "semantic_fallback"
            if semantic_score >= 0.16 or fit_bonus >= 0.18
            else "tmdb_recs"
        )

        results.append(
            {
                "tmdb_id": rid,
                "title": title_val,
                "poster_path": poster_path,
                "poster_url": details.get("poster_url"),
                "overview": details.get("overview"),
                "first_air_date": details.get("first_air_date"),
                "vote_average": vote_average,
                "vote_count": vote_count,
                "popularity": details.get("popularity"),
                "genres": details.get("genres"),
                "genre_ids": details.get("genre_ids"),
                "source": source,
                "score": round(float(total_score), 4),
            }
        )

        if len(results) >= MAX_RESULTS:
            break

    results.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    print("SEO final rec count:", len(results))

    if len(results) < MIN_RESULTS:
        fallback_res = await db.execute(
            text(
                """
                SELECT
                    show_id,
                    title,
                    poster_path
                FROM shows
                WHERE show_id <> :tmdb_id
                  AND poster_path IS NOT NULL
                ORDER BY title ASC
                LIMIT 200
                """
            ),
            {"tmdb_id": tmdb_id},
        )

        fallback_rows = fallback_res.mappings().all()

        for r in fallback_rows:
            sid = int(r["show_id"])
            if sid in seen_ids:
                continue

            det = await _tmdb_details(sid)
            fits_anchor, fit_bonus = _candidate_fit_adjustment(anchor_profile, det)
            if not fits_anchor:
                continue

            det_genre_names = _genre_name_set(det)
            det_genre_ids = set(det.get("genre_ids") or [])
            det_semantic = _semantic_text_score(
                anchor_keywords,
                det.get("title") or det.get("name"),
                det.get("overview"),
                " ".join(det.get("genres") or []),
            )
            det_genre_score = _genre_overlap_score(anchor_genre_ids, det_genre_ids)

            if anchor_profile["grounded_drama"] and "drama" not in det_genre_names:
                continue
            if anchor_profile["period"] and fit_bonus < 0.12 and det_semantic < 0.12:
                continue
            if anchor_profile["medical_family"] and fit_bonus < 0.10 and det_semantic < 0.10:
                continue
            if det_genre_score < 0.08 and det_semantic < 0.10 and fit_bonus < 0.10:
                continue

            seen_ids.add(sid)
            results.append(
                {
                    "tmdb_id": sid,
                    "title": r["title"],
                    "poster_path": r["poster_path"],
                    "poster_url": f"https://image.tmdb.org/t/p/w500{r['poster_path']}" if r["poster_path"] else None,
                    "overview": det.get("overview"),
                    "first_air_date": det.get("first_air_date"),
                    "vote_average": det.get("vote_average"),
                    "vote_count": det.get("vote_count"),
                    "popularity": det.get("popularity"),
                    "genres": det.get("genres") or [],
                    "genre_ids": det.get("genre_ids") or [],
                    "source": "fallback",
                    "score": round(float(max(fit_bonus, det_semantic, det_genre_score)), 4),
                }
            )

            if len(results) >= MIN_RESULTS:
                break

    page_copy = _build_page_copy(str(row["title"]), results[:MAX_RESULTS])

    return {
        "anchor": {
            "tmdb_id": row["show_id"],
            "title": row["title"],
            "poster_path": row["poster_path"],
        },
        "recommendations": results[:MAX_RESULTS],
        "page_copy": page_copy,
    }


@router.get("/best-crime")
async def best_crime(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
        SELECT show_id, title, poster_path
        FROM shows
        WHERE lower(title) IN (
            'breaking bad',
            'the wire',
            'the sopranos',
            'true detective',
            'peaky blinders',
            'top boy',
            'dexter',
            'the shield'
        )
    """))

    return res.mappings().all()


@router.get("/best-scifi")
async def best_scifi(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
        SELECT show_id, title, poster_path
        FROM shows
        WHERE lower(title) IN (
            'dark',
            'black mirror',
            'lost',
            'the x-files',
            'stranger things',
            'the mandalorian'
        )
    """))

    return res.mappings().all()


@router.get("/best-like-breaking-bad")
async def best_like_breaking_bad(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
        SELECT s.show_id, s.title, s.poster_path
        FROM reddit_pairs rp
        JOIN shows s
          ON s.show_id = rp.tmdb_id_b
        WHERE rp.tmdb_id_a = 1396
        ORDER BY rp.pair_weight DESC
        LIMIT 24
    """))

    return res.mappings().all()


@router.get("/best-drama")
async def best_drama(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
       SELECT show_id, title, poster_path
        FROM shows
        WHERE lower(title) IN (
            'breaking bad',
            'better call saul',
            'the sopranos',
            'the wire',
            'succession',
            'the last of us',
            'true detective',
            'the night of',
            'fargo',
            'peaky blinders',
            'dark',
            'the white lotus'
        )
    """))

    return res.mappings().all()
