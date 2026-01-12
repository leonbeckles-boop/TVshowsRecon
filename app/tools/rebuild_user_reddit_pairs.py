# app/tools/rebuild_user_reddit_pairs.py

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.services.reddit_pairs_build import (
    ensure_user_reddit_pairs_table,
    rebuild_pairs_for_all_users,
    rebuild_pairs_for_user,
)


async def _run(user_id: int | None, limit: int, wipe_all: bool) -> None:
    async with AsyncSessionLocal() as session:  # type: ignore[call-arg]
        assert isinstance(session, AsyncSession)

        # ensure table exists
        await ensure_user_reddit_pairs_table(session)

        if wipe_all:
            print("Wiping user_reddit_pairs…")
            await session.execute(text("TRUNCATE TABLE user_reddit_pairs;"))
            await session.commit()

        if user_id is not None:
            n = await rebuild_pairs_for_user(session, user_id, limit=limit)
            print(f"Rebuilt reddit pairs for user {user_id}: {n} rows.")
        else:
            n = await rebuild_pairs_for_all_users(session, limit=limit)
            print(f"Rebuilt reddit pairs for ALL users: {n} rows total.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild per-user reddit recommendations into user_reddit_pairs."
    )
    parser.add_argument(
        "--user",
        type=int,
        default=None,
        help="If set, only rebuild for this user_id. Otherwise rebuild for all.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max number of suggestions per user (default 500).",
    )
    parser.add_argument(
        "--wipe-all",
        action="store_true",
        help="Truncate user_reddit_pairs before rebuilding.",
    )

    args = parser.parse_args()
    asyncio.run(_run(args.user, args.limit, args.wipe_all))


if __name__ == "__main__":
    main()
