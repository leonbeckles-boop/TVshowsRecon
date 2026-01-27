from __future__ import annotations
from alembic import op

revision = "368ea2d1418b"
down_revision = "2d41e64ea71c"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.execute("""
    CREATE TABLE IF NOT EXISTS show_embeddings (
        tmdb_id BIGINT PRIMARY KEY,
        embedding vector(1536) NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id INTEGER PRIMARY KEY,
        embedding vector(1536) NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    """)

    op.execute("""
    CREATE INDEX IF NOT EXISTS ix_show_embeddings_embedding
    ON show_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
    """)

    op.execute("""
    CREATE INDEX IF NOT EXISTS ix_user_profiles_embedding
    ON user_profiles
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);
    """)

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_profiles_embedding;")
    op.execute("DROP INDEX IF EXISTS ix_show_embeddings_embedding;")
    op.execute("DROP TABLE IF EXISTS user_profiles;")
    op.execute("DROP TABLE IF EXISTS show_embeddings;")
