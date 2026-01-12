
# app/services/reddit_backfill_tmdb_ids_sync.py
# Synchronous, transaction-safe backfill for reddit_posts.tmdb_id.
# It avoids async sessions entirely (no asyncio.run), and commits/rolls back per row.
#
# Usage inside backend container:
#   python -m app.services.reddit_backfill_tmdb_ids_sync --limit 500 --subs televisionsuggestions --commit
#
# If you omit --commit it runs in DRY-RUN mode.

from __future__ import annotations

import argparse
import logging
import re
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

# Your project-local imports
from app.database import SessionLocal  # sync session factory
from app.db_models import RedditPost

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _pick_tmdb_search():
    """Return a callable search_tv(q) -> list[dict], trying multiple helpers in your repo."""
    # 1) tmdb_cached
    try:
        from app.services import tmdb_cached
        if hasattr(tmdb_cached, "search_tv"):
            def _search_tv(q: str):
                return tmdb_cached.search_tv(q, limit=5)  # type: ignore
            logger.info("Using tmdb_cached.search_tv()")
            return _search_tv
    except Exception as e:
        logger.debug("tmdb_cached.search_tv unavailable: %s", e)

    # 2) tmdb_service
    try:
        from app.services import tmdb_service
        if hasattr(tmdb_service, "search_tv"):
            def _search_tv(q: str):
                return tmdb_service.search_tv(q, limit=5)  # type: ignore
            logger.info("Using tmdb_service.search_tv()")
            return _search_tv
    except Exception as e:
        logger.debug("tmdb_service.search_tv unavailable: %s", e)

    # 3) tmdb
    try:
        from app.services import tmdb
        if hasattr(tmdb, "search_tv"):
            def _search_tv(q: str):
                return tmdb.search_tv(q, limit=5)  # type: ignore
            logger.info("Using tmdb.search_tv()")
            return _search_tv
    except Exception as e:
        logger.debug("tmdb.search_tv unavailable: %s", e)

    # 4) title_to_tmdb (lookup id)
    try:
        from app.services import title_to_tmdb
        if hasattr(title_to_tmdb, "lookup_tmdb_id"):
            def _search_tv(q: str):
                tid = title_to_tmdb.lookup_tmdb_id(q)  # type: ignore
                return [{"id": tid, "name": q}] if tid else []
            logger.info("Using title_to_tmdb.lookup_tmdb_id()")
            return _search_tv
    except Exception as e:
        logger.debug("title_to_tmdb.lookup_tmdb_id unavailable: %s", e)

    raise RuntimeError("No TMDB search helper found (tmdb_cached/tmdb_service/tmdb/title_to_tmdb)")


def _clean_query(title: str) -> str:
    t = (title or "").strip()
    t = re.sub(r"\[[^\]]+\]", "", t)  # remove [Request], [Help], etc.
    t = re.sub(r"^(looking for|recommend(ation)?s? for|suggest(ions)? for)\s+", "", t, flags=re.I)
    t = t.rstrip(" ?!.:").strip()

    m = re.findall(r'"([^"]{2,70})"', t)
    if m:
        return m[0].strip()

    split = re.split(r"\b(and|but)\b", t, maxsplit=1, flags=re.I)
    if split:
        return split[0].strip()

    return t


def _extract_candidate_queries(title: str) -> List[str]:
    cleaned = _clean_query(title)
    out = [cleaned] if cleaned else []
    for q in re.findall(r'"([^"]{2,70})"', title or ""):
        q2 = q.strip()
        if q2 and q2.lower() not in {x.lower() for x in out}:
            out.append(q2)
    # unique case-insensitive, cap attempts
    uniq = []
    seen = set()
    for q in out:
        k = q.lower()
        if k not in seen and q:
            seen.add(k)
            uniq.append(q)
    return uniq[:4]


def _best_tmdb_id(results: List[dict]) -> Optional[int]:
    for r in results or []:
        tid = r.get("id") or r.get("tmdb_id") or r.get("tmdbId")
        if isinstance(tid, int):
            return tid
        try:
            if tid and str(tid).isdigit():
                return int(tid)
        except Exception:
            pass
    return None


def backfill(limit: int = 300, subs: Optional[List[str]] = None, dry_run: bool = True) -> dict:
    search_tv = _pick_tmdb_search()

    filters = [RedditPost.tmdb_id.is_(None)]
    if subs:
        filters.append(RedditPost.subreddit.in_(subs))

    scanned = matched = updated = failed = 0
    examples: List[str] = []

    with SessionLocal() as db:
        rows = db.execute(select(RedditPost).where(*filters).order_by(RedditPost.id.desc()).limit(limit)).scalars().all()
        scanned = len(rows)
        for row in rows:
            queries = _extract_candidate_queries(row.title or "")
            tmdb_id: Optional[int] = None
            for q in queries:
                try:
                    res = search_tv(q) or []
                    tmdb_id = _best_tmdb_id(res)
                    if tmdb_id:
                        break
                except Exception as e:
                    if len(examples) < 5:
                        examples.append(f"search error for '{q}': {e}")
                    continue

            if tmdb_id:
                matched += 1
                if not dry_run:
                    try:
                        row.tmdb_id = tmdb_id
                        db.add(row)
                        db.commit()
                        updated += 1
                    except SQLAlchemyError as e:
                        db.rollback()
                        failed += 1
                        if len(examples) < 5:
                            examples.append(f"commit error for id={row.id}: {e}")
            else:
                if len(examples) < 5:
                    examples.append(f"no match for id={row.id} title='{row.title}'")

    return {
        "scanned": scanned,
        "matched": matched,
        "updated": updated,
        "failed": failed,
        "examples": examples,
        "dry_run": dry_run,
    }


def main():
    ap = argparse.ArgumentParser(description="Backfill reddit_posts.tmdb_id (sync & safe).")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--subs", type=str, default="")
    ap.add_argument("--commit", action="store_true", help="Write updates (omit for dry-run)")

    args = ap.parse_args()
    subs = [s.strip() for s in args.subs.split(",") if s.strip()] if args.subs else None

    stats = backfill(limit=args.limit, subs=subs, dry_run=(not args.commit))
    logger.info("Backfill done: %s", stats)
    print(stats)


if __name__ == "__main__":
    main()
