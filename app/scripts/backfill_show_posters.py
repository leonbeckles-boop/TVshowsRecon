import asyncio
import os
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv


TMDB_BASE = "https://api.themoviedb.org/3"
BATCH_SIZE = 50
REQUEST_TIMEOUT = 20.0
SLEEP_BETWEEN_REQUESTS = 0.05


def normalize_db_url(raw_url: str) -> str:
    """
    Normalize common Postgres URL variants for SQLAlchemy async usage.
    """
    if raw_url.startswith("postgresql+asyncpg://"):
        return raw_url
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw_url


def get_database_url() -> str:
    candidates = [
        os.getenv("DATABASE_URL"),
        os.getenv("RENDER_DATABASE_URL"),
        os.getenv("POSTGRES_URL"),
    ]
    for value in candidates:
        if value:
            return normalize_db_url(value)
    raise RuntimeError(
        "No database URL found. Set DATABASE_URL or another supported DB env var."
    )


def get_tmdb_api_key() -> str:
    candidates = [
        os.getenv("TMDB_API_KEY"),
        os.getenv("TMDB_BEARER_TOKEN"),
    ]
    for value in candidates:
        if value:
            return value
    raise RuntimeError("TMDB_API_KEY not found in environment.")


async def fetch_tmdb_tv_details(
    client: httpx.AsyncClient, tmdb_api_key: str, tmdb_id: int
) -> Optional[dict]:
    url = f"{TMDB_BASE}/tv/{tmdb_id}"
    params = {"api_key": tmdb_api_key}

    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[WARN] TMDb fetch failed for {tmdb_id}: {exc}")
        return None


async def backfill_posters(dry_run: bool = True, limit: Optional[int] = None) -> None:
    load_dotenv()

    database_url = get_database_url()
    tmdb_api_key = get_tmdb_api_key()

    engine = create_async_engine(database_url, future=True, echo=False)

    select_sql = """
        SELECT show_id, title, external_id, poster_path
        FROM shows
        WHERE poster_path IS NULL OR poster_path = ''
        ORDER BY show_id
    """

    if limit is not None:
        select_sql += " LIMIT :limit"

    update_sql = text(
        """
        UPDATE shows
        SET poster_path = :poster_path
        WHERE show_id = :show_id
        """
    )

    total_scanned = 0
    total_updated = 0
    total_missing_on_tmdb = 0
    total_failed = 0

    async with engine.begin() as conn:
        params = {"limit": limit} if limit is not None else {}
        result = await conn.execute(text(select_sql), params)
        rows = result.mappings().all()

    print(f"[INFO] Found {len(rows)} shows with missing poster_path")

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with engine.begin() as conn:
            for start in range(0, len(rows), BATCH_SIZE):
                batch = rows[start : start + BATCH_SIZE]
                print(
                    f"[INFO] Processing batch {start + 1}-{start + len(batch)} of {len(rows)}"
                )

                for row in batch:
                    total_scanned += 1

                    try:
                        show_id = int(row["show_id"])
                        title = row["title"]
                    except Exception:
                        total_failed += 1
                        print(f"[WARN] Bad row skipped: {row}")
                        continue

                    details = await fetch_tmdb_tv_details(client, tmdb_api_key, show_id)
                    await asyncio.sleep(SLEEP_BETWEEN_REQUESTS)

                    if not details:
                        total_missing_on_tmdb += 1
                        print(f"[MISS] {show_id} | {title} | no TMDb details")
                        continue

                    poster_path = details.get("poster_path")
                    if not poster_path:
                        total_missing_on_tmdb += 1
                        print(f"[MISS] {show_id} | {title} | no poster on TMDb")
                        continue

                    if dry_run:
                        print(f"[DRY] {show_id} | {title} -> {poster_path}")
                        total_updated += 1
                        continue

                    await conn.execute(
                        update_sql,
                        {
                            "show_id": show_id,
                            "poster_path": poster_path,
                        },
                    )
                    total_updated += 1
                    print(f"[OK] {show_id} | {title} -> {poster_path}")

    await engine.dispose()

    print("\n=== SUMMARY ===")
    print(f"Scanned: {total_scanned}")
    print(f"Would update / Updated: {total_updated}")
    print(f"Missing on TMDb: {total_missing_on_tmdb}")
    print(f"Failed rows: {total_failed}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill missing poster_path values in shows from TMDb."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually write updates to the database. Default is dry run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N missing rows.",
    )

    args = parser.parse_args()

    asyncio.run(backfill_posters(dry_run=not args.live, limit=args.limit))