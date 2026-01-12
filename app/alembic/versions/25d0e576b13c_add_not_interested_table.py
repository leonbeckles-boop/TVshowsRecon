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


def upgrade() -> None:
    op.create_table(
        "not_interested",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "tmdb_id",
            name="uq_not_interested_user_tmdb",
        ),
        # If your DB has a `users` table, uncomment the FK below.
        # If you’re unsure, run without the FK first to avoid coupling.
        # sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_not_interested_user"),
    )

    # Add the indexes explicitly (helpful on some backends)
    op.create_index("ix_not_interested_user_id", "not_interested", ["user_id"])
    op.create_index("ix_not_interested_tmdb_id", "not_interested", ["tmdb_id"])


def downgrade() -> None:
    op.drop_index("ix_not_interested_tmdb_id", table_name="not_interested")
    op.drop_index("ix_not_interested_user_id", table_name="not_interested")
    op.drop_table("not_interested")