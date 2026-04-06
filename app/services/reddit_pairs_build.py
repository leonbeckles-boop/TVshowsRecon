from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_user_reddit_pairs_table(session: AsyncSession) -> None:
    """
    Make sure the user_reddit_pairs table + indexes exist.

    Columns:
      - user_id           INT
      - suggested_tmdb_id BIGINT
      - weight            DOUBLE PRECISION
      - updated_at        TIMESTAMPTZ DEFAULT now()
    """

    ddl_table = """
        CREATE TABLE IF NOT EXISTS user_reddit_pairs (
            user_id            INTEGER NOT NULL,
            suggested_tmdb_id  BIGINT  NOT NULL,
            weight             DOUBLE PRECISION NOT NULL,
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, suggested_tmdb_id)
        );
    """

    ddl_idx_user = """
        CREATE INDEX IF NOT EXISTS ix_user_reddit_pairs_user
            ON user_reddit_pairs (user_id);
    """

    ddl_idx_weight = """
        CREATE INDEX IF NOT EXISTS ix_user_reddit_pairs_weight
            ON user_reddit_pairs (weight DESC);
    """

    ddl_idx_suggested = """
        CREATE INDEX IF NOT EXISTS ix_user_reddit_pairs_suggested
            ON user_reddit_pairs (suggested_tmdb_id);
    """

    await session.execute(text(ddl_table))
    await session.execute(text(ddl_idx_user))
    await session.execute(text(ddl_idx_weight))
    await session.execute(text(ddl_idx_suggested))
    await session.commit()


_SQL_USER_AGG_FROM_REDDIT = text(
    """
    WITH seeds AS (
        SELECT tmdb_id
        FROM user_favorites
        WHERE user_id = :uid
    ),
    blocked AS (
        SELECT tmdb_id
        FROM user_favorites
        WHERE user_id = :uid

        UNION

        SELECT tmdb_id
        FROM not_interested
        WHERE user_id = :uid
    ),
    both_dirs AS (
        SELECT rp.tmdb_id_b AS suggested, rp.pair_weight AS w
        FROM reddit_pairs rp
        JOIN seeds s ON s.tmdb_id = rp.tmdb_id_a

        UNION ALL

        SELECT rp.tmdb_id_a AS suggested, rp.pair_weight AS w
        FROM reddit_pairs rp
        JOIN seeds s ON s.tmdb_id = rp.tmdb_id_b
    ),
    agg AS (
        SELECT suggested, SUM(w) AS w
        FROM both_dirs
        WHERE suggested NOT IN (SELECT tmdb_id FROM blocked)
        GROUP BY suggested
    )
    SELECT suggested AS suggested_tmdb_id, w
    FROM agg
    ORDER BY w DESC
    LIMIT :limit
    """
)


async def rebuild_pairs_for_user(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int = 500,
    ensure_table: bool = True,
) -> int:
    """
    Rebuild reddit-based pairs for a single user into user_reddit_pairs.

    1) Take their favorites from user_favorites.
    2) Walk the reddit_pairs graph in both directions.
    3) Aggregate weights per suggested_tmdb_id.
    4) Normalise weights so the top item is 1.0.
    5) Upsert into user_reddit_pairs.
    """

    if ensure_table:
        await ensure_user_reddit_pairs_table(session)

    res = await session.execute(_SQL_USER_AGG_FROM_REDDIT, {"uid": user_id, "limit": limit})
    rows = res.all()

    await session.execute(
        text("DELETE FROM user_reddit_pairs WHERE user_id = :uid"),
        {"uid": user_id},
    )

    if not rows:
        await session.commit()
        return 0

    weights = [float(r.w) for r in rows]  # type: ignore[attr-defined]
    max_w = max(weights) if weights else 0.0
    if max_w <= 0:
        await session.commit()
        return 0

    normalised = [
        (user_id, int(r.suggested_tmdb_id), float(r.w) / max_w)  # type: ignore[attr-defined]
        for r in rows
    ]

    insert_stmt = text(
        """
        INSERT INTO user_reddit_pairs (user_id, suggested_tmdb_id, weight)
        VALUES (:uid, :sid, :w)
        ON CONFLICT (user_id, suggested_tmdb_id)
        DO UPDATE SET
            weight     = EXCLUDED.weight,
            updated_at = now()
        """
    )

    payload = [{"uid": uid, "sid": sid, "w": w} for (uid, sid, w) in normalised]

    await session.execute(insert_stmt, payload)
    await session.commit()

    return len(normalised)


async def rebuild_pairs_for_all_users(
    session: AsyncSession,
    *,
    limit: int = 500,
) -> int:
    """
    Rebuild reddit-based pairs for all users that have favorites.

    Returns the total number of user_reddit_pairs rows written.
    """

    await ensure_user_reddit_pairs_table(session)

    res = await session.execute(text("SELECT DISTINCT user_id FROM user_favorites"))
    user_ids = [int(row.user_id) for row in res]  # type: ignore[attr-defined]

    total = 0
    for uid in user_ids:
        n = await rebuild_pairs_for_user(
            session,
            uid,
            limit=limit,
            ensure_table=False,
        )
        total += n

    return total