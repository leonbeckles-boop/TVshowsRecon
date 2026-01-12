from __future__ import annotations

import os
import asyncio
import logging
from typing import Optional

from . import reddit_ingest

logger = logging.getLogger(__name__)

SCHEDULE_MINUTES = int(os.getenv("REDDIT_SCHEDULE_MINUTES", "60"))

FAVOURITES_INGEST_USER_ID: Optional[int] = None
try:
    raw_uid = os.getenv("FAVOURITES_INGEST_USER_ID")
    if raw_uid:
        FAVOURITES_INGEST_USER_ID = int(raw_uid)
except Exception:
    FAVOURITES_INGEST_USER_ID = None


async def _tick_once() -> None:
    try:
        await reddit_ingest.run_ingest()
    except Exception as e:
        logger.warning("[Reddit] global ingest failed: %s", e)

    if FAVOURITES_INGEST_USER_ID is not None:
        try:
            await reddit_ingest.run_ingest(user_id=FAVOURITES_INGEST_USER_ID)
        except Exception as e:
            logger.warning("[Reddit] favourites ingest failed for user_id=%s: %s", FAVOURITES_INGEST_USER_ID, e)


async def run_scheduler_forever() -> None:
    period = max(1, SCHEDULE_MINUTES)
    logger.info("[Reddit] Ingest scheduler started. period=%s min, favourites_user=%s", period, FAVOURITES_INGEST_USER_ID)
    while True:
        await _tick_once()
        try:
            await asyncio.sleep(period * 60)
        except asyncio.CancelledError:
            break
    logger.info("[Reddit] Ingest scheduler stopped.")
