from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.routes.recs_v3 import (
    _tmdb_api_key,
    _tmdb_details,
    _tmdb_recommendations_for_fav,
)

import asyncio
import math

router = APIRouter(prefix="/api/seo", tags=["seo"])

MIN_RESULTS = 12
MAX_RESULTS = 24


@router.get("/shows-like/{slug}")
async def shows_like(
    slug: str,
    db: AsyncSession = Depends(get_async_session),
):
    title = slug.replace("-", " ")

    # 1) Resolve slug -> anchor show
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

    # 2) Pull TMDB recommendations + reddit_pairs in parallel
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
            res = await db.execute(reddit_sql, {"tid": tmdb_id, "lim": MAX_RESULTS * 2})
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

    tmdb_task = _tmdb_recommendations_for_fav(tmdb_id, api_key, max_n=MAX_RESULTS * 2)
    tmdb_ids_raw, reddit_scores = await asyncio.gather(tmdb_task, _fetch_reddit_similar())

    # 3) Merge scores
    merged_scores: dict[int, float] = {}

    # TMDB recs get a strong base weight
    for rid in (tmdb_ids_raw or []):
        if not isinstance(rid, int) or rid == tmdb_id:
            continue
        merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.65

    # Reddit pair score adds "fan overlap" signal
    for rid, pw in (reddit_scores or {}).items():
        if rid == tmdb_id:
            continue
        reddit_score = 0.55 * math.log10(1.0 + max(pw, 0.0))
        merged_scores[rid] = merged_scores.get(rid, 0.0) + reddit_score

    # 4) Sort candidate IDs by merged score
    sorted_ids = sorted(merged_scores.keys(), key=lambda x: merged_scores[x], reverse=True)

    # 5) Fetch details for ranked IDs
    fetch_ids = sorted_ids[: MAX_RESULTS * 3]
    details_list = await asyncio.gather(*[_tmdb_details(rid) for rid in fetch_ids])

    results: list[dict] = []
    seen_ids = {tmdb_id}

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

        # Light quality / relevance filtering
        if 10767 in genre_ids or 10766 in genre_ids:
            # talk / soap
            continue
        if 99 in genre_ids and len(genre_ids) == 1:
            # pure documentary only
            continue

        vote_count = int(details.get("vote_count") or 0)
        vote_average = float(details.get("vote_average") or 0.0)

        # filter obvious junk
        if vote_count < 20 and vote_average < 6.5:
            continue

        seen_ids.add(rid)

        results.append(
            {
                "tmdb_id": rid,
                "title": title_val,
                "poster_path": poster_path,
                "poster_url": details.get("poster_url"),
                "overview": details.get("overview"),
                "first_air_date": details.get("first_air_date"),
                "vote_average": details.get("vote_average"),
                "vote_count": details.get("vote_count"),
                "popularity": details.get("popularity"),
                "genres": details.get("genres"),
                "genre_ids": details.get("genre_ids"),
                "source": (
                    "multi_signal"
                    if rid in reddit_scores and rid in set(tmdb_ids_raw or [])
                    else "reddit_pairs"
                    if rid in reddit_scores
                    else "tmdb_recs"
                ),
                "score": round(float(merged_scores.get(rid, 0.0)), 4),
            }
        )

        if len(results) >= MAX_RESULTS:
            break

    print("SEO final rec count:", len(results))

    # 6) Small backup fallback if still too short
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