"""merge heads

Revision ID: b390702d1e53
Revises: 368ea2d1418b, bfb9952645a7
Create Date: 2026-01-27 19:13:28.190463

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b390702d1e53'
down_revision: Union[str, Sequence[str], None] = ('368ea2d1418b', 'bfb9952645a7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
