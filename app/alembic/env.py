# alembic/env.py
from __future__ import annotations
import os, sys
from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection
from app.core.settings import settings
from app.db_models import Base

target_metadata = Base.metadata

# --- Make sure we can import your app, and load .env ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))   # .../alembic
PROJECT_PARENT = os.path.dirname(PROJECT_ROOT)              # project root
if PROJECT_PARENT not in sys.path:
    sys.path.insert(0, PROJECT_PARENT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass



config = context.config

# Choose a **sync** URL for Alembic
url_sync = os.getenv("DATABASE_URL_SYNC")
if not url_sync:
    # Fallback: derive sync URL from async URL by swapping driver
    if settings.database_url and "+asyncpg" in settings.database_url:
        url_sync = settings.database_url.replace("+asyncpg", "+psycopg2")
    else:
        url_sync = settings.database_url  # may already be sync

if not url_sync:
    raise RuntimeError("No DATABASE_URL_SYNC set and cannot derive from DATABASE_URL")

# Tell Alembic the connection URL
config.set_main_option("sqlalchemy.url", url_sync)

# Optional: print for sanity
print("ALEMBIC_SYNC_URL:", config.get_main_option("sqlalchemy.url"))

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)



def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode (SYNC engine)."""
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
