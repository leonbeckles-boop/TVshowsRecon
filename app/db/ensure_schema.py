# app/db/ensure_schema.py
from __future__ import annotations

import logging
import inspect
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text

log = logging.getLogger(__name__)

# We depend on the project's async session factory.
try:
    from app.db.session import get_async_session  # returns an async generator
except Exception as e:  # pragma: no cover
    get_async_session = None  # type: ignore
    log.error("get_async_session not importable: %s", e)

@asynccontextmanager
async def _session_cm():
    """Wrap get_async_session() so we can 'async with' it safely."""
    if get_async_session is None:
        raise RuntimeError("get_async_session is unavailable")

    obj = get_async_session()
    # If it's an async generator, drive it using acontextmanager semantics
    if inspect.isasyncgen(obj):
        agen = obj  # type: ignore
        try:
            sess = await agen.__anext__()
            yield sess
        except StopAsyncIteration:  # pragma: no cover
            raise RuntimeError("get_async_session produced no session")
        finally:
            try:
                await agen.aclose()
            except Exception as e:  # pragma: no cover
                log.debug("aclose failed: %s", e)
    else:
        # If it's already a context manager/Session
        async with obj as sess:  # type: ignore
            yield sess

async def ensure_schema() -> None:
    """Idempotent, non-fatal schema tweaks for reddit tables.
    Never raises; logs and continues so the app can start even if DB is unavailable.
    """
    statements = [
        """
        ALTER TABLE reddit_posts
          ADD COLUMN IF NOT EXISTS num_comments INTEGER NOT NULL DEFAULT 0
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_reddit_posts_subreddit
          ON reddit_posts (subreddit)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_reddit_posts_created
          ON reddit_posts (created_utc)
        """
    ]

    try:
        async with _session_cm() as session:
            for stmt in statements:
                try:
                    await session.execute(text(stmt))
                except Exception as e:
                    log.warning("ensure_schema: statement failed (continuing). sql=%s err=%s", stmt.strip(), e)
            try:
                await session.commit()
                log.info("ensure_schema: schema verified/updated.")
            except Exception as e:
                log.warning("ensure_schema: commit failed (continuing). err=%s", e)
    except Exception as e:
        log.error("ensure_schema: fatal error (continuing startup). err=%s", e)