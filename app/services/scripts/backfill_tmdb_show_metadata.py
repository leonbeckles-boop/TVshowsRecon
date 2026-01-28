from __future__ import annotations

import asyncio
import os
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

TMDB_API = "https://api.themoviedb.org/3"
TMDB_KEY = os.getenv("TMDB_API_KEY") or os.getenv("TMDB_KEY")

# How fast we hit TMDB (keep gentle)
REQUEST_DELAY_S = float(os.getenv("TMDB_BACKFILL_DELAY", "0.25"))
BATCH_SIZE = int(os.getenv("TMDB_BACKFILL_BATCH", "25"))
MAX_RETRIES = int(os.getenv("TMDB_BACKFILL_RETRIES", "3"))

# If you connect to Render/hosted PG, you typically need SSL.
# For asyncpg we pass ssl via connect_args and strip sslmode from URL.
FORCE_ASYNCPG_SSL = os.getenv("FORCE_ASYNCPG_SSL", "1").lower() not in ("0", "false", "no")


def _strip_query_param(url: str, key: str) -> str:
    """Remove a query parameter from a URL (case-insensitive key match)."""
    if not url:
        return url
    parts = urlsplit(url)
    q = [(k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != key.lower()]
    new_query = urlencode(q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _to_asyncpg(url: str) -> str:
    """
    Convert a sync psycopg URL -> asyncpg for async SQLAlchemy engine.
    Accepts postgres:// shorthand too.
    Also strips sslmode=... because asyncpg doesn't accept it as a kwarg.
    """
    u = (url or "").strip()
    if not u:
        return u

    # remove sslmode from query for asyncpg
    u = _strip_query_param(u, "sslmode")

    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://") :]

    u = u.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    u = u.replace("postgresql+psycopg2://", "postgresql+asyncpg://")

    # If plain postgresql://, pick asyncpg
    if u.startswith("postgresql://"):
        u = "postgresql+asyncpg://" + u[len("postgresql://") :]

    return u


def _parse_date_yyyy_mm_dd(s: Optional[str]) -> Optional[date]:
    """Convert 'YYYY-MM-DD' -> datetime.date, else None."""
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


async def _tmdb_get_tv(tmdb_id: int, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    if not TMDB_KEY:
        raise RuntimeError("TMDB_API_KEY is not set")

    url = f"{TMDB_API}/tv/{tmdb_id}"
    params = {"api_key": TMDB_KEY}

    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json() or {}
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                # TMDB rate limit: obey Retry-After if present
                ra = r.headers.get("Retry-After")
                sleep_s = float(ra) if ra and ra.isdigit() else (1.0 + attempt)
                await asyncio.sleep(sleep_s)
                continue

            last_err = RuntimeError(f"TMDB {r.status_code}: {r.text[:200]}")
        except Exception as e:
            last_err = e

        await asyncio.sleep(0.5 * attempt)

    if last_err:
        raise last_err
    return None


def _extract_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    genres = [g.get("name") for g in (data.get("genres") or []) if g and g.get("name")]
    networks = [n.get("name") for n in (data.get("networks") or []) if n and n.get("name")]

    return {
        "overview": data.get("overview") or None,
        "genres": genres or None,
        "networks": networks or None,
        # IMPORTANT: date object, not string (fixes asyncpg toordinal error)
        "first_air_date": _parse_date_yyyy_mm_dd(data.get("first_air_date")),
        "popularity": float(data.get("popularity") or 0.0),
        "vote_average": float(data.get("vote_average") or 0.0),
        "vote_count": int(data.get("vote_count") or 0),
        "poster_path": data.get("poster_path") or None,
    }


async def _fetch_rows_to_update(session: AsyncSession, limit: int) -> List[Tuple[int, str, str]]:
    """
    Returns [(show_id, external_id, title), ...] for rows missing metadata.
    external_id holds TMDB TV id as text.
    """
    q = text(
        """
        SELECT show_id, external_id, title
        FROM shows
        WHERE external_id IS NOT NULL
          AND (
              overview IS NULL
              OR poster_path IS NULL
          )
        ORDER BY show_id
        LIMIT :lim
        """
    )
    res = await session.execute(q, {"lim": limit})
    rows = res.mappings().all()
    out: List[Tuple[int, str, str]] = []
    for r in rows:
        out.append((int(r["show_id"]), str(r["external_id"]), str(r["title"] or "")))
    return out


async def _update_show(session: AsyncSession, show_id: int, fields: Dict[str, Any]) -> None:
    q = text(
        """
        UPDATE shows
        SET
          overview = COALESCE(:overview, overview),
          genres = COALESCE(:genres, genres),
          networks = COALESCE(:networks, networks),
          first_air_date = COALESCE(:first_air_date, first_air_date),
          popularity = COALESCE(:popularity, popularity),
          vote_average = COALESCE(:vote_average, vote_average),
          vote_count = COALESCE(:vote_count, vote_count),
          poster_path = COALESCE(:poster_path, poster_path)
          tmdb_checked_at = now()
        WHERE show_id = :show_id
        """
    )
    payload = dict(fields)
    payload["show_id"] = show_id
    await session.execute(q, payload)


async def main() -> None:
    if not TMDB_KEY:
        raise SystemExit("TMDB_API_KEY (or TMDB_KEY) must be set in your environment.")

    db_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_ASYNC") or os.getenv("ALEMBIC_SYNC_URL")
    if not db_url:
        raise SystemExit("Set DATABASE_URL (preferred) or ALEMBIC_SYNC_URL so we can connect to Postgres.")

    db_url_async = _to_asyncpg(db_url)

    connect_args = {}
    if FORCE_ASYNCPG_SSL:
        connect_args["ssl"] = True

    engine = create_async_engine(db_url_async, pool_pre_ping=True, connect_args=connect_args)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_updated = 0
    started = time.time()

    # Prevent repeating the same TMDB id within a single run
    seen_tmdb_ids: set[int] = set()

    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            async with SessionLocal() as session:
                rows = await _fetch_rows_to_update(session, limit=BATCH_SIZE)
                if not rows:
                    break

                for show_id, external_id, title in rows:
                    try:
                        tmdb_id = int(external_id)
                    except Exception:
                        print(f"SKIP show_id={show_id} bad external_id={external_id!r} title={title}")
                        continue

                    if tmdb_id in seen_tmdb_ids:
                        continue
                    seen_tmdb_ids.add(tmdb_id)

                    try:
                        data = await _tmdb_get_tv(tmdb_id, client)
                        if not data:
                            print(f"MISS tmdb_id={tmdb_id} show_id={show_id} title={title}")
                            continue

                        fields = _extract_fields(data)
                        await _update_show(session, show_id, fields)
                        await session.commit()
                        total_updated += 1

                        print(f"OK   show_id={show_id} tmdb_id={tmdb_id} title={title}")

                    except Exception as e:
                        await session.rollback()
                        print(f"ERR  show_id={show_id} tmdb_id={tmdb_id} title={title} err={e}")

                    await asyncio.sleep(REQUEST_DELAY_S)

    await engine.dispose()

    elapsed = time.time() - started
    print(f"\nDone. Updated ~{total_updated} rows in {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
