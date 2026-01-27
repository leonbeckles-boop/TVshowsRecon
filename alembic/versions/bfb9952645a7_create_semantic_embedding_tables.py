"""create semantic embedding tables

Revision ID: bfb9952645a7
Revises: 2d41e64ea71c
Create Date: 2026-01-27 13:52:59.352600

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfb9952645a7'
down_revision: Union[str, Sequence[str], None] = '2d41e64ea71c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
