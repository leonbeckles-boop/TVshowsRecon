# app/services/scripts/backfill_show_embeddings.py
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# OpenAI 1.x SDK
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

# ---- Config ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# 1536 dims -> matches your table vector(1536)
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

BATCH_SIZE = int(os.getenv("EMBED_BACKFILL_BATCH", "50"))
SLEEP_S = float(os.getenv("EMBED_BACKFILL_DELAY", "0.2"))

# IMPORTANT: Use a *sync* URL here (psycopg)
DB_URL = os.getenv("ALEMBIC_SYNC_URL") or os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL")

client = OpenAI(api_key=OPENAI_API_KEY)


def build_embed_text(row: Dict[str, Any]) -> str:
    """
    Deterministic, high-signal text for embedding.
    Keep it stable so embeddings are comparable over time.
    """
    title = (row.get("title") or "").strip()
    overview = (row.get("overview") or "").strip()

    genres = row.get("genres") or []
    networks = row.get("networks") or []

    # these are text[] columns; depending on driver they may come as list already
    if isinstance(genres, str):
        genres = [genres]
    if isinstance(networks, str):
        networks = [networks]

    g = ", ".join([x for x in genres if x]) if genres else ""
    n = ", ".join([x for x in networks if x]) if networks else ""

    parts = [
        f"Title: {title}",
        f"Overview: {overview}" if overview else "",
        f"Genres: {g}" if g else "",
        f"Networks: {n}" if n else "",
        "Type: TV series",
    ]
    # keep it compact-ish
    return "\n".join([p for p in parts if p]).strip()


def connect_engine() -> Engine:
    if not DB_URL:
        raise SystemExit("Set ALEMBIC_SYNC_URL (recommended) or DATABASE_URL_SYNC / DATABASE_URL.")
    if DB_URL.startswith("postgresql+asyncpg://"):
        raise SystemExit("Use a sync URL for this script (psycopg), e.g. ALEMBIC_SYNC_URL.")
    return create_engine(DB_URL, pool_pre_ping=True)


def fetch_candidates(engine: Engine, limit: int) -> List[Dict[str, Any]]:
    q = text(
        """
        SELECT
          COALESCE(tmdb_id::bigint, external_id::bigint) AS tmdb_id,
          title,
          overview,
          genres,
          networks
        FROM shows
        WHERE (tmdb_id IS NOT NULL OR external_id IS NOT NULL)
          AND title IS NOT NULL
          AND (overview IS NOT NULL OR genres IS NOT NULL OR networks IS NOT NULL)
          AND COALESCE(tmdb_id::bigint, external_id::bigint) NOT IN (
              SELECT tmdb_id FROM show_embeddings WHERE embedding IS NOT NULL
          )
        ORDER BY show_id
        LIMIT :lim
        """
    )
    with engine.begin() as conn:
        rows = conn.execute(q, {"lim": limit}).mappings().all()
        return [dict(r) for r in rows]


@retry(stop=stop_after_attempt(4), wait=wait_exponential_jitter(initial=1, max=10))
def embed_texts(texts: List[str]) -> List[List[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def upsert_embeddings(engine: Engine, items: List[Tuple[int, List[float]]]) -> None:
    q = text(
        """
        INSERT INTO show_embeddings (tmdb_id, embedding, updated_at)
        VALUES (:tmdb_id, :embedding, now())
        ON CONFLICT (tmdb_id) DO UPDATE
        SET embedding = EXCLUDED.embedding,
            updated_at = now()
        """
    )
    payload = [{"tmdb_id": tmdb_id, "embedding": vec} for tmdb_id, vec in items]
    with engine.begin() as conn:
        conn.execute(q, payload)


def main() -> None:
    if not OPENAI_API_KEY:
        raise SystemExit("Set OPENAI_API_KEY in your environment.")
    engine = connect_engine()

    total = 0
    started = time.time()

    while True:
        rows = fetch_candidates(engine, limit=BATCH_SIZE)
        if not rows:
            break

        texts: List[str] = []
        ids: List[int] = []
        for r in rows:
            tmdb_id = int(r["tmdb_id"])
            ids.append(tmdb_id)
            texts.append(build_embed_text(r))

        vectors = embed_texts(texts)
        upsert_embeddings(engine, list(zip(ids, vectors)))

        total += len(ids)
        print(f"Embedded {len(ids)} shows (total={total})")
        time.sleep(SLEEP_S)

    elapsed = time.time() - started
    print(f"\nDone. Embedded {total} shows in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
