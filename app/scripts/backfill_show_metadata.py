import asyncio
import os
from datetime import date
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


TMDB_BASE = "https://api.themoviedb.org/3"
REQUEST_TIMEOUT = 20.0
SLEEP_BETWEEN_REQUESTS = 0.05



# Candidate columns we may backfill if they exist
CANDIDATE_COLUMNS = [
    "poster_path",
    "backdrop_path",
    "overview",
    "first_air_date",
    "vote_average",
    "vote_count",
    "popularity",
    "original_language",
    "origin_country",
    "name",
    "title",
]


def normalize_db_url(raw_url: str) -> str:
    if raw_url.startswith("postgresql+asyncpg://"):
        return raw_url
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw_url


def get_database_url() -> str:
    for key in ("DATABASE_URL", "RENDER_DATABASE_URL", "POSTGRES_URL"):
        val = os.getenv(key)
        if val:
            return normalize_db_url(val)
    raise RuntimeError("No database URL found in environment.")


def get_tmdb_api_key() -> str:
    key = os.getenv("TMDB_API_KEY")
    if not key:
        raise RuntimeError("TMDB_API_KEY not found in environment.")
    return key


async def fetch_tmdb_tv_details(
    client: httpx.AsyncClient,
    tmdb_api_key: str,
    tmdb_id: int,
) -> Optional[dict[str, Any]]:
    url = f"{TMDB_BASE}/tv/{tmdb_id}"
    try:
        resp = await client.get(url, params={"api_key": tmdb_api_key})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[WARN] Failed TMDb fetch for {tmdb_id}: {exc}")
        return None


async def get_show_columns(conn: AsyncConnection) -> list[dict[str, str]]:
    res = await conn.execute(
        text(
            """
            SELECT
                column_name,
                data_type,
                udt_name
            FROM information_schema.columns
            WHERE table_name = 'shows'
            ORDER BY ordinal_position
            """
        )
    )
    return [
        {
            "column_name": str(r[0]),
            "data_type": str(r[1]),
            "udt_name": str(r[2]),
        }
        for r in res.fetchall()
    ]


def classify_column(col: str, data_type: str, udt_name: str) -> str:
    dt = data_type.lower()
    udt = udt_name.lower()

    if dt in {"character varying", "text", "character"}:
        return "text"
    if dt == "date":
        return "date"
    if dt in {"integer", "bigint", "smallint"}:
        return "int"
    if dt in {"numeric", "real", "double precision", "decimal"}:
        return "float"
    if dt == "array" or udt.startswith("_"):
        return "array"

    # fallback by known column names
    if col in {"poster_path", "backdrop_path", "overview", "original_language", "name", "title"}:
        return "text"
    if col == "first_air_date":
        return "date"
    if col in {"vote_count"}:
        return "int"
    if col in {"vote_average", "popularity"}:
        return "float"
    if col == "origin_country":
        return "array"

    return "other"


def build_missing_condition(column_types: dict[str, str]) -> str:
    checks: list[str] = []

    for col, kind in column_types.items():
        if kind == "text":
            checks.append(f"({col} IS NULL OR {col} = '')")
        elif kind == "date":
            checks.append(f"{col} IS NULL")
        elif kind in {"int", "float"}:
            checks.append(f"{col} IS NULL")
        elif kind == "array":
            checks.append(f"({col} IS NULL OR array_length({col}, 1) IS NULL)")
        else:
            checks.append(f"{col} IS NULL")

    return " OR ".join(checks) if checks else "FALSE"


def parse_tmdb_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None

    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def coerce_value_for_column(col: str, kind: str, details: dict[str, Any]) -> Any:
    if col == "poster_path":
        return details.get("poster_path")
    if col == "backdrop_path":
        return details.get("backdrop_path")
    if col == "overview":
        return details.get("overview")
    if col == "first_air_date":
        return parse_tmdb_date(details.get("first_air_date"))
    if col == "vote_average":
        val = details.get("vote_average")
        return float(val) if val is not None else None
    if col == "vote_count":
        val = details.get("vote_count")
        return int(val) if val is not None else None
    if col == "popularity":
        val = details.get("popularity")
        return float(val) if val is not None else None
    if col == "original_language":
        return details.get("original_language")
    if col == "origin_country":
        val = details.get("origin_country")
        return val if isinstance(val, list) else None
    if col == "name":
        return details.get("name")
    if col == "title":
        return details.get("name") or details.get("title")

    # generic fallback
    value = details.get(col)
    if kind == "date":
        return parse_tmdb_date(value)
    return value


def is_missing_value(kind: str, value: Any) -> bool:
    if value is None:
        return True
    if kind == "text" and isinstance(value, str):
        return value.strip() == ""
    if kind == "array" and isinstance(value, list):
        return len(value) == 0
    return False


def build_update_statement(columns: list[str]) -> Any:
    set_parts = [f"{col} = :{col}" for col in columns]
    sql = f"""
        UPDATE shows
        SET {", ".join(set_parts)}
        WHERE show_id = :show_id
    """
    return text(sql)


async def main(dry_run: bool = True, limit: Optional[int] = None) -> None:
    load_dotenv()

    database_url = get_database_url()
    tmdb_api_key = get_tmdb_api_key()
    engine: AsyncEngine = create_async_engine(database_url, future=True, echo=False)

    async with engine.connect() as conn:
        column_rows = await get_show_columns(conn)

    all_columns = [row["column_name"] for row in column_rows]

    if "show_id" not in all_columns:
        raise RuntimeError("shows.show_id column not found.")
    if "title" not in all_columns:
        raise RuntimeError("shows.title column not found.")

    available_columns = [c for c in CANDIDATE_COLUMNS if c in all_columns]
    if not available_columns:
        raise RuntimeError("No supported columns found to backfill.")

    column_types: dict[str, str] = {}
    for row in column_rows:
        col = row["column_name"]
        if col in available_columns:
            column_types[col] = classify_column(col, row["data_type"], row["udt_name"])

    print("[INFO] Found shows columns:", ", ".join(all_columns))
    print("[INFO] Will backfill columns:", ", ".join(available_columns))

    missing_condition = build_missing_condition(column_types)

    select_sql = f"""
        SELECT show_id, title
        FROM shows
        WHERE {missing_condition}
        ORDER BY show_id
    """
    if limit is not None:
        select_sql += " LIMIT :limit"

    async with engine.connect() as conn:
        result = await conn.execute(
            text(select_sql),
            {"limit": limit} if limit is not None else {},
        )
        rows = result.mappings().all()

    print(f"[INFO] Found {len(rows)} rows with at least one missing target field")

    updated_rows = 0
    missing_on_tmdb = 0
    failed_rows = 0
    no_new_data_rows = 0

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with engine.begin() as conn:
            for row in rows:
                try:
                    show_id = int(row["show_id"])
                    title = str(row["title"])
                except Exception:
                    failed_rows += 1
                    print(f"[WARN] Bad row skipped: {row}")
                    continue

                details = await fetch_tmdb_tv_details(client, tmdb_api_key, show_id)
                await asyncio.sleep(SLEEP_BETWEEN_REQUESTS)

                if not details:
                    missing_on_tmdb += 1
                    print(f"[MISS] {show_id} | {title} | no TMDb details")
                    continue

                current_res = await conn.execute(
                    text("SELECT * FROM shows WHERE show_id = :show_id LIMIT 1"),
                    {"show_id": show_id},
                )
                current = current_res.mappings().first()
                if not current:
                    failed_rows += 1
                    print(f"[WARN] Row disappeared before update: {show_id} | {title}")
                    continue

                update_payload: dict[str, Any] = {"show_id": show_id}
                changed_cols: list[str] = []

                for col in available_columns:
                    kind = column_types[col]
                    current_val = current.get(col)
                    new_val = coerce_value_for_column(col, kind, details)

                    current_missing = is_missing_value(kind, current_val)
                    new_missing = is_missing_value(kind, new_val)

                    if current_missing and not new_missing:
                        update_payload[col] = new_val
                        changed_cols.append(col)

                if not changed_cols:
                    no_new_data_rows += 1
                    print(f"[SKIP] {show_id} | {title} | nothing new to fill")
                    continue

                if dry_run:
                    preview = ", ".join(f"{c}={update_payload[c]!r}" for c in changed_cols)
                    print(f"[DRY] {show_id} | {title} | {preview}")
                    updated_rows += 1
                    continue

                stmt = build_update_statement(changed_cols)
                await conn.execute(stmt, update_payload)
                updated_rows += 1
                print(f"[OK] {show_id} | {title} | filled: {', '.join(changed_cols)}")

    await engine.dispose()

    print("\n=== SUMMARY ===")
    print(f"Rows with new data filled / would fill: {updated_rows}")
    print(f"Rows missing on TMDb: {missing_on_tmdb}")
    print(f"Rows with nothing new available: {no_new_data_rows}")
    print(f"Failed rows: {failed_rows}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill missing show metadata from TMDb into the shows table."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually write updates. Default is dry run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N qualifying rows.",
    )
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.live, limit=args.limit))