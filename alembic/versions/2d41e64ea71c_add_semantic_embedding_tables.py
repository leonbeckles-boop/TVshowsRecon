"""add semantic embedding tables

Revision ID: 2d41e64ea71c
Revises: f3110f124c61
Create Date: 2026-01-27 10:37:34.811581

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d41e64ea71c'
down_revision: Union[str, Sequence[str], None] = 'f3110f124c61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
