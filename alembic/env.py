# alembic/env.py
from __future__ import annotations

import os, sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# --- Make sure we can import your app, and load .env ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))   # .../alembic
PROJECT_PARENT = os.path.dirname(PROJECT_ROOT)              # project root
if PROJECT_PARENT not in sys.path:
    sys.path.insert(0, PROJECT_PARENT)

try:
    from dotenv import load_dotenv
    # IMPORTANT: do NOT override shell env vars
    load_dotenv(override=False)
except Exception:
    pass

from app.core.settings import settings  # noqa: E402
from app.db_models import Base          # noqa: E402

target_metadata = Base.metadata
config = context.config


# ----------------------------
# URL normalization helpers
# ----------------------------

def _to_sync_psycopg(url: str) -> str:
    """Normalize to sync psycopg v3 URL for Alembic."""
    u = (url or "").strip()
    if not u:
        return u

    # Accept postgres:// shorthand
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://"):]

    # Ensure psycopg v3 driver
    if u.startswith("postgresql://"):
        u = "postgresql+psycopg://" + u[len("postgresql://"):]

    # Convert async -> sync
    u = u.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    u = u.replace("+asyncpg", "+psycopg")

    # Convert any old psycopg2 -> psycopg
    u = u.replace("postgresql+psycopg2://", "postgresql+psycopg://")
    u = u.replace("+psycopg2", "+psycopg")

    return u


def _choose_sync_url() -> str:
    """
    Priority:
    1) ALEMBIC_SYNC_URL     (best for local -> Render)
    2) DATABASE_URL_SYNC
    3) DATABASE_URL
    4) settings.database_url
    """

    for key in ("ALEMBIC_SYNC_URL", "DATABASE_URL_SYNC", "DATABASE_URL"):
        v = os.getenv(key)
        if v:
            print(f"ALEMBIC picked env var {key}")
            return _to_sync_psycopg(v)

    if getattr(settings, "database_url", None):
        print("ALEMBIC fell back to settings.database_url")
        return _to_sync_psycopg(settings.database_url)

    return ""


# ----------------------------
# Final URL selection
# ----------------------------

url_sync = _choose_sync_url()

if not url_sync:
    raise RuntimeError(
        "No DB URL found for Alembic. "
        "Set ALEMBIC_SYNC_URL (recommended) "
        "or DATABASE_URL_SYNC, or DATABASE_URL."
    )

config.set_main_option("sqlalchemy.url", url_sync)

print("ALEMBIC using database URL:", config.get_main_option("sqlalchemy.url"))


# ----------------------------
# Logging
# ----------------------------

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ----------------------------
# Migration runners
# ----------------------------

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
