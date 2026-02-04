# app/services/scripts/backfill_show_embeddings_local.py
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from sentence_transformers import SentenceTransformer


# ---- Config ----
MODEL_NAME = os.getenv("LOCAL_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
BATCH_SIZE = int(os.getenv("EMBED_BACKFILL_BATCH", "64"))
SLEEP_S = float(os.getenv("EMBED_BACKFILL_DELAY", "0.05"))

DB_URL = os.getenv("ALEMBIC_SYNC_URL") or os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL")


def build_embed_text(row: Dict[str, Any]) -> str:
    title = (row.get("title") or "").strip()
    overview = (row.get("overview") or "").strip()

    genres = row.get("genres") or []
    networks = row.get("networks") or []

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
    engine = connect_engine()
    model = SentenceTransformer(MODEL_NAME)

    total = 0
    t0 = time.time()

    while True:
        rows = fetch_candidates(engine, limit=BATCH_SIZE)
        if not rows:
            break

        ids: List[int] = []
        texts: List[str] = []
        for r in rows:
            ids.append(int(r["tmdb_id"]))
            texts.append(build_embed_text(r))

        # Returns np.ndarray (batch, dim). Convert to python lists for SQLAlchemy.
        vecs = model.encode(texts, normalize_embeddings=True).tolist()

        upsert_embeddings(engine, list(zip(ids, vecs)))

        total += len(ids)
        print(f"Embedded {len(ids)} shows (total={total})")
        time.sleep(SLEEP_S)

    print(f"\nDone. Embedded {total} shows in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
