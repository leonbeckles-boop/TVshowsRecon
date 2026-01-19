"""baseline from current DB

Revision ID: 4192ba3cd80d
Revises: 
Create Date: 2025-09-13 19:57:15.056590

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4192ba3cd80d'
down_revision = "42b2b492a2da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This migration was originally generated to "baseline" an already-existing database.
    # On a fresh database (Render production), there is nothing to baseline.
    pass



def downgrade() -> None:
    pass

