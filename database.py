# database.py
import os
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# ✅ add these for correct typing of generator dependencies
from collections.abc import AsyncGenerator, Iterator

load_dotenv()


ASYNC_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://tvuser:tvpass@localhost:5432/tvrecs",
)
SYNC_DSN = os.getenv(
    "DATABASE_URL_SYNC",
    "postgresql+psycopg://tvuser:tvpass@localhost:5432/tvrecs",
)

Base = declarative_base()

# --- Async engine/session (for async endpoints)
async_engine = create_async_engine(ASYNC_DSN, future=True, pool_pre_ping=True)
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine, expire_on_commit=False, autoflush=False, autocommit=False
)

# --- Sync engine/session (CLI, Alembic, simple scripts)
engine = create_engine(SYNC_DSN, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# FastAPI dependencies
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # nothing extra; context manager handles close
            ...

def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
