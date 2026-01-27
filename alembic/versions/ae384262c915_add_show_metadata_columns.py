from alembic import op

revision = "ae384262c915"
down_revision = "b390702d1e53"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Use IF NOT EXISTS so it’s safe if prod already has the columns
    op.execute("ALTER TABLE shows ADD COLUMN IF NOT EXISTS overview TEXT;")
    op.execute("ALTER TABLE shows ADD COLUMN IF NOT EXISTS genres TEXT[];")
    op.execute("ALTER TABLE shows ADD COLUMN IF NOT EXISTS networks TEXT[];")
    op.execute("ALTER TABLE shows ADD COLUMN IF NOT EXISTS first_air_date DATE;")
    op.execute("ALTER TABLE shows ADD COLUMN IF NOT EXISTS popularity DOUBLE PRECISION;")
    op.execute("ALTER TABLE shows ADD COLUMN IF NOT EXISTS vote_average DOUBLE PRECISION;")
    op.execute("ALTER TABLE shows ADD COLUMN IF NOT EXISTS vote_count INTEGER;")

def downgrade() -> None:
    # Downgrade drops columns (ok locally; you probably won’t run downgrades in prod)
    op.execute("ALTER TABLE shows DROP COLUMN IF EXISTS vote_count;")
    op.execute("ALTER TABLE shows DROP COLUMN IF EXISTS vote_average;")
    op.execute("ALTER TABLE shows DROP COLUMN IF EXISTS popularity;")
    op.execute("ALTER TABLE shows DROP COLUMN IF EXISTS first_air_date;")
    op.execute("ALTER TABLE shows DROP COLUMN IF EXISTS networks;")
    op.execute("ALTER TABLE shows DROP COLUMN IF EXISTS genres;")
    op.execute("ALTER TABLE shows DROP COLUMN IF EXISTS overview;")
