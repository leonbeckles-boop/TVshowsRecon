# app/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from app.services.reddit_ingest import ingest_once

_scheduler: AsyncIOScheduler | None = None

def start_jobs():
    global _scheduler
    if _scheduler:
        return _scheduler
    _scheduler = AsyncIOScheduler()
    # every 15 minutes, pull 30 posts per subreddit
    _scheduler.add_job(ingest_once, "interval", minutes=15, kwargs={"limit": 30}, id="reddit_ingest")
    _scheduler.start()
    return _scheduler

def stop_jobs():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
