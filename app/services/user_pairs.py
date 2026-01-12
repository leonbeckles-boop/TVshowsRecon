# app/services/user_pairs.py
"""
Personalised reddit pair builder.

Quick strategy (fast and good-enough to start):
- For a given user_id, take their favourites.
- Copy all rows from the *global* reddit_pairs where anchor_tmdb_id in favourites.
- Upsert them into user_reddit_pairs with that user_id, keeping the same weight.
Why this helps: the user's graph becomes limited to their anchors, which removes
irrelevant anchors from other users and makes weighting personal out-of-the-box.
You can evolve this later to mine posts specifically for the user's favs.
"""

from __future__ import annotations

from typing import Sequence, Tuple
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy import text

# --- helpers ---------------------------------------------------------------

FAVS_SQL = text("""
    SELECT tmdb_id
    FROM favorite_show
    WHERE user_id = :uid
""")

DELETE_SQL = text("""
    DELETE FROM user_reddit_pairs WHERE user_id = :uid
""")

INSERT_FROM_GLOBAL = text("""
    INSERT INTO user_reddit_pairs (user_id, anchor_tmdb_id, suggested_tmdb_id, weight, first_seen_at, last_seen_at)
    SELECT :uid as user_id, rp.anchor_tmdb_id, rp.suggested_tmdb_id, rp.weight, now(), now()
    FROM reddit_pairs rp
    WHERE rp.anchor_tmdb_id = ANY(:anchor_ids)
    ON CONFLICT (user_id, anchor_tmdb_id, suggested_tmdb_id)
    DO UPDATE SET
        weight = EXCLUDED.weight,
        last_seen_at = now()
""")


async def rebuild_user_pairs(session: AsyncSession, user_id: int) -> dict:
    # gather anchors
    anchors = [row[0] for row in (await session.execute(FAVS_SQL, {"uid": user_id})).all()]
    # clear existing
    await session.execute(DELETE_SQL, {"uid": user_id})
    if not anchors:
        await session.commit()
        return {"user_id": user_id, "anchors": 0, "inserted": 0}
    # bulk insert
    await session.execute(INSERT_FROM_GLOBAL, {"uid": user_id, "anchor_ids": anchors})
    await session.commit()
    # return count for confirmation
    count = (await session.execute(text("SELECT COUNT(*) FROM user_reddit_pairs WHERE user_id=:uid"), {"uid": user_id})).scalar_one()
    return {"user_id": user_id, "anchors": len(anchors), "inserted": int(count)}
