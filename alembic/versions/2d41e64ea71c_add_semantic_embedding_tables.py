from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2d41e64ea71c"
down_revision = "f3110f124c61"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Enable pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # show_embeddings table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS show_embeddings (
            tmdb_id BIGINT PRIMARY KEY,
            embedding vector(1536) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # user_profiles table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            embedding vector(1536) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # Indexes for fast ANN search
    # Choose cosine distance (recommended when embeddings are unit-normalized or cosine-based)
    # If you prefer L2, use vector_l2_ops instead.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_show_embeddings_embedding
        ON show_embeddings
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_profiles_embedding
        ON user_profiles
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 50);
        """
    )


def downgrade() -> None:
    # Drop indexes first (safe even if they don't exist)
    op.execute("DROP INDEX IF EXISTS ix_user_profiles_embedding;")
    op.execute("DROP INDEX IF EXISTS ix_show_embeddings_embedding;")

    op.execute("DROP TABLE IF EXISTS user_profiles;")
    op.execute("DROP TABLE IF EXISTS show_embeddings;")
