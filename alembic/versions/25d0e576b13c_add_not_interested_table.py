"""add not_interested table

Revision ID: 25d0e576b13c
Revises: 53ea5aefc2b6
Create Date: 2025-09-17 16:19:17.505768

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25d0e576b13c'
down_revision: Union[str, Sequence[str], None] = '53ea5aefc2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    # Prefer to_regclass over SQLAlchemy inspection: it's simpler and avoids
    # schema/search_path surprises.
    return bind.execute(
        sa.text("SELECT to_regclass(:n) IS NOT NULL OR to_regclass('public.' || :n) IS NOT NULL"),
        {"n": name},
    ).scalar()


def _column_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    # Idempotent: don't fail if the table already exists.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS not_interested (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            tmdb_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_not_interested_user_tmdb UNIQUE (user_id, tmdb_id)
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_not_interested_user_id ON not_interested (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_not_interested_tmdb_id ON not_interested (tmdb_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_not_interested_tmdb_id")
    op.execute("DROP INDEX IF EXISTS ix_not_interested_user_id")
    op.execute("DROP TABLE IF EXISTS not_interested")