"""add user_ratings table

Revision ID: a48dad0a93fb
Revises: c351ef259ffe
Create Date: 2025-09-11 11:43:48.892843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c1b2d8a9f0b'
down_revision = 'c351ef259ffe'
branch_labels = None
depends_on = None



def upgrade():
    op.create_table(
        "user_rating",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("tmdb_id", sa.Integer, index=True, nullable=False),
        sa.Column("title", sa.String(300)),
        sa.Column("rating", sa.Float, nullable=False),
        sa.Column("watched_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("seasons_completed", sa.Integer),
        sa.Column("notes", sa.String(1000)),
        sa.UniqueConstraint("user_id", "tmdb_id", name="uq_rating_user_show"),
    )
    # FIX: correct table name
    op.create_unique_constraint("uq_fav_user_show", "favorites_tmdb", ["user_id", "tmdb_id"])

def downgrade():
    # FIX: correct table name
    op.drop_constraint("uq_fav_user_show", "favorites_tmdb", type_="unique")
    op.drop_table("user_rating")