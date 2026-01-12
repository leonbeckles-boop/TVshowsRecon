# app/db/session.py
import os
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _normalise_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().strip('"').strip("'")


def _to_async_driver(url: str) -> str:
    """
    Ensure the SQLAlchemy URL uses the async driver.
    - postgresql+psycopg:// -> postgresql+asyncpg://
    - postgresql://          -> postgresql+asyncpg://
    - postgresql+asyncpg://  -> (as is)
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg://"):
        return "postgresql+asyncpg://" + url.split("postgresql+psycopg://", 1)[1]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("postgresql://", 1)[1]
    # Fallback: do nothing
    return url


# Read envs
DATABASE_URL = _normalise_url(os.getenv("DATABASE_URL"))
ASYNC_DATABASE_URL = _normalise_url(os.getenv("ASYNC_DATABASE_URL"))

# Derive async URL if needed
if not ASYNC_DATABASE_URL and DATABASE_URL:
    ASYNC_DATABASE_URL = _to_async_driver(DATABASE_URL)

if not ASYNC_DATABASE_URL:
    raise RuntimeError(
        "No ASYNC_DATABASE_URL (and no usable DATABASE_URL) found. "
        "Set DATABASE_URL like 'postgresql+psycopg://user:pass@db:5432/dbname' "
        "or ASYNC_DATABASE_URL like 'postgresql+asyncpg://user:pass@db:5432/dbname'."
    )

# Create async engine/session factory
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session
