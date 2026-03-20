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
        merged_scores[rid] = merged_scores.get(rid, 0.0) + min(0.12, 0.05 + 0.08 * raw)

    for rid, pw in (reddit_scores or {}).items():
        if rid == tmdb_id:
            continue
        reddit_score = 1.25 * math.log10(1.0 + max(pw, 0.0))
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

        if is_tmdb and not is_reddit:
            if genre_score < 0.10 and semantic_score < 0.12:
                continue
            if genre_score == 0.0 and vote_average < 7.2:
                continue

        if not is_reddit and genre_score < 0.08 and semantic_score < 0.10:
            continue

        total_score = float(merged_scores.get(rid, 0.0))
        total_score += 0.65 * semantic_score
        total_score += 0.35 * genre_score
        total_score += qual_bonus

        if is_tmdb and not is_reddit:
            total_score *= 0.68

        if is_trending and not is_reddit and semantic_score >= 0.16:
            total_score += 0.08

        seen_ids.add(rid)

        source = (
            "multi_signal"
            if is_reddit and (is_tmdb or is_trending)
            else "reddit_pairs"
            if is_reddit
            else "semantic_fallback"
            if semantic_score >= 0.14
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
                LIMIT 100
                """
            ),
            {"tmdb_id": tmdb_id},
        )

        fallback_rows = fallback_res.mappings().all()

        for r in fallback_rows:
            sid = int(r["show_id"])
            if sid in seen_ids:
                continue

            seen_ids.add(sid)
            results.append(
                {
                    "tmdb_id": sid,
                    "title": r["title"],
                    "poster_path": r["poster_path"],
                    "poster_url": f"https://image.tmdb.org/t/p/w500{r['poster_path']}" if r["poster_path"] else None,
                    "overview": None,
                    "first_air_date": None,
                    "vote_average": None,
                    "vote_count": None,
                    "popularity": None,
                    "genres": [],
                    "genre_ids": [],
                    "source": "fallback",
                    "score": 0.0,
                }
            )

            if len(results) >= MIN_RESULTS:
                break

    return {
        "anchor": {
            "tmdb_id": row["show_id"],
            "title": row["title"],
            "poster_path": row["poster_path"],
        },
        "recommendations": results[:MAX_RESULTS],
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
