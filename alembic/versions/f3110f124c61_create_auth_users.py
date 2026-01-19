"""create auth_users

Revision ID: f3110f124c61
Revises: 25d0e576b13c
Create Date: 2025-10-08 20:39:09.069949

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3110f124c61'
down_revision: Union[str, Sequence[str], None] = '25d0e576b13c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _scalar(sql: str, params: dict | None = None):
    """Return first column of first row, or None."""
    bind = op.get_bind()
    res = bind.execute(sa.text(sql), params or {})
    row = res.first()
    return None if row is None else row[0]


def _table_exists(name: str) -> bool:
    # to_regclass returns NULL if the relation doesn't exist
    return _scalar("SELECT to_regclass(:rel)", {"rel": f"public.{name}"}) is not None


def _column_exists(table: str, col: str) -> bool:
    if not _table_exists(table):
        return False
    return bool(
        _scalar(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:t AND column_name=:c
            LIMIT 1
            """,
            {"t": table, "c": col},
        )
    )


def _index_exists(_table: str, index_name: str) -> bool:
    # Index is its own relation
    return _scalar("SELECT to_regclass(:idx)", {"idx": f"public.{index_name}"}) is not None


def _unique_exists(table: str, constraint_name: str) -> bool:
    if not _table_exists(table):
        return False
    return bool(
        _scalar(
            """
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass(:rel)
              AND conname = :c
              AND contype = 'u'
            LIMIT 1
            """,
            {"rel": f"public.{table}", "c": constraint_name},
        )
    )


def _fk_exists(table: str, constrained_cols: list[str], referred_table: str) -> bool:
    # Best-effort check; if anything is off, we'll just try creating the FK guarded.
    if not _table_exists(table) or not _table_exists(referred_table):
        return False
    # Compare by referred table + constrained column names.
    return bool(
        _scalar(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND t.relname = :table
              AND c.contype = 'f'
              AND c.confrelid = to_regclass(:referred)
              AND (
                SELECT array_agg(att.attname ORDER BY u.ord)
                FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
                JOIN pg_attribute att ON att.attrelid = c.conrelid AND att.attnum = u.attnum
              ) = :cols
            LIMIT 1
            """,
            {"table": table, "referred": f"public.{referred_table}", "cols": constrained_cols},
        )
    )


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE:
    # This revision was originally generated while *migrating* from an older schema
    # (users/user_rating/favorites_tmdb/etc) to the current auth_users + library tables.
    # On fresh or already-updated DBs these DROP statements are destructive and/or fail.
    #
    # So we make this migration safe/idempotent by ONLY applying the forward-looking
    # changes we still need, and guarding each operation.

    # ---- auth_users tweaks ----
    if _table_exists("auth_users"):
        if not _column_exists("auth_users", "username"):
            op.add_column("auth_users", sa.Column("username", sa.String(length=255), nullable=True))

        # Ensure created_at is non-null (safe even if already non-null)
        if _column_exists("auth_users", "created_at"):
            op.alter_column(
                "auth_users",
                "created_at",
                existing_type=postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                existing_server_default=sa.text("now()"),
            )

        # Add a unique constraint if missing. We do this inside a DO block so that
        # if it already exists (or was created under a different migration run),
        # we don't abort the entire transaction.
        op.execute(
            """
            DO $$
            BEGIN
              BEGIN
                ALTER TABLE auth_users
                  ADD CONSTRAINT uq_auth_users_email UNIQUE (email);
              EXCEPTION WHEN duplicate_object OR duplicate_table THEN
                -- constraint already exists
              END;
            END $$;
            """
        )

    # ---- not_interested compatibility ----
    if _table_exists("not_interested"):
        # IMPORTANT: this table may already exist (and may already have data).
        # Adding a NOT NULL column can fail if rows already exist, which aborts the whole
        # migration transaction (and then any subsequent reflection helpers also fail).
        # So we add tmdb_id as NULLable first, backfill it from legacy show_id if present,
        # and only then enforce NOT NULL when safe.
        if not _column_exists("not_interested", "tmdb_id"):
            op.add_column("not_interested", sa.Column("tmdb_id", sa.Integer(), nullable=True))

        # Backfill tmdb_id from old show_id if that column exists.
        if _column_exists("not_interested", "show_id"):
            op.execute(
                "UPDATE not_interested SET tmdb_id = show_id WHERE tmdb_id IS NULL"
            )

        # Enforce NOT NULL only if there are no remaining NULLs.
        op.execute(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM not_interested WHERE tmdb_id IS NULL) THEN
                ALTER TABLE not_interested ALTER COLUMN tmdb_id SET NOT NULL;
              END IF;
            END $$;
            """
        )

        # Old schema cleanup (only if those columns exist)
        if _column_exists("not_interested", "reason"):
            op.drop_column("not_interested", "reason")
        if _column_exists("not_interested", "show_id"):
            # drop FK first if present (name may vary, so use IF EXISTS SQL)
            op.execute("ALTER TABLE not_interested DROP CONSTRAINT IF EXISTS not_interested_show_id_fkey")
            op.drop_column("not_interested", "show_id")

        # Ensure index + unique constraint exist
        if not _index_exists("not_interested", op.f("ix_not_interested_tmdb_id")):
            op.create_index(op.f("ix_not_interested_tmdb_id"), "not_interested", ["tmdb_id"], unique=False)

        # Drop old unique if it exists, then ensure new one exists
        op.execute("ALTER TABLE not_interested DROP CONSTRAINT IF EXISTS uq_not_interested_user_show")
        if not _unique_exists("not_interested", "uq_not_interested_user_tmdb"):
            op.create_unique_constraint("uq_not_interested_user_tmdb", "not_interested", ["user_id", "tmdb_id"])

        # Point FK at auth_users if auth_users exists
        if _table_exists("auth_users") and not _fk_exists("not_interested", ["user_id"], "auth_users"):
            # Drop any legacy FK first (name may vary)
            op.execute("ALTER TABLE not_interested DROP CONSTRAINT IF EXISTS not_interested_user_id_fkey")
            op.create_foreign_key(
                None,
                "not_interested",
                "auth_users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # ---- Optional, best-effort column/index normalisations ----
    # These are safe to skip if the tables are already in the desired shape.
    if _table_exists("reddit_posts"):
        if _column_exists("reddit_posts", "reddit_id"):
            op.alter_column(
                "reddit_posts",
                "reddit_id",
                existing_type=sa.VARCHAR(length=20),
                type_=sa.String(length=32),
                nullable=True,
            )
        if _column_exists("reddit_posts", "title"):
            op.alter_column(
                "reddit_posts",
                "title",
                existing_type=sa.TEXT(),
                type_=sa.String(length=500),
                existing_nullable=False,
            )
        if _column_exists("reddit_posts", "url"):
            op.alter_column(
                "reddit_posts",
                "url",
                existing_type=sa.TEXT(),
                type_=sa.String(length=1000),
                nullable=False,
            )
        if _column_exists("reddit_posts", "score"):
            op.alter_column(
                "reddit_posts",
                "score",
                existing_type=sa.INTEGER(),
                nullable=True,
                existing_server_default=sa.text("0"),
            )
        if _column_exists("reddit_posts", "subreddit"):
            op.alter_column(
                "reddit_posts",
                "subreddit",
                existing_type=sa.VARCHAR(length=64),
                type_=sa.String(length=200),
                nullable=True,
            )
        # Index changes: drop old if exists, ensure new ones exist
        op.execute("DROP INDEX IF EXISTS ix_reddit_posts_subreddit")
        if not _index_exists("reddit_posts", op.f("ix_reddit_posts_created_utc")):
            op.create_index(op.f("ix_reddit_posts_created_utc"), "reddit_posts", ["created_utc"], unique=False)
        if not _index_exists("reddit_posts", op.f("ix_reddit_posts_show_id")):
            op.create_index(op.f("ix_reddit_posts_show_id"), "reddit_posts", ["show_id"], unique=False)
        if _column_exists("reddit_posts", "num_comments"):
            op.drop_column("reddit_posts", "num_comments")

    if _table_exists("shows"):
        if _column_exists("shows", "title"):
            op.alter_column(
                "shows",
                "title",
                existing_type=sa.VARCHAR(length=255),
                type_=sa.String(length=300),
                existing_nullable=False,
            )
        if _column_exists("shows", "poster_url"):
            op.alter_column(
                "shows",
                "poster_url",
                existing_type=sa.TEXT(),
                type_=sa.String(length=500),
                existing_nullable=True,
            )
        op.execute("ALTER TABLE shows DROP CONSTRAINT IF EXISTS shows_external_id_key")
        if _column_exists("shows", "external_id") and not _index_exists("shows", op.f("ix_shows_external_id")):
            op.create_index(op.f("ix_shows_external_id"), "shows", ["external_id"], unique=False)

        # Drop legacy columns if they exist
        for col in ["cast", "created_at", "genres", "platforms", "language", "description"]:
            if _column_exists("shows", col):
                op.drop_column("shows", col)


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('shows', sa.Column('description', sa.TEXT(), autoincrement=False, nullable=True))
    op.add_column('shows', sa.Column('language', sa.VARCHAR(length=50), autoincrement=False, nullable=True))
    op.add_column('shows', sa.Column('platforms', postgresql.ARRAY(sa.VARCHAR()), autoincrement=False, nullable=True))
    op.add_column('shows', sa.Column('genres', postgresql.ARRAY(sa.VARCHAR()), autoincrement=False, nullable=True))
    op.add_column('shows', sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True))
    op.add_column('shows', sa.Column('cast', postgresql.ARRAY(sa.VARCHAR()), autoincrement=False, nullable=True))
    op.drop_index(op.f('ix_shows_external_id'), table_name='shows')
    op.create_unique_constraint('shows_external_id_key', 'shows', ['external_id'], postgresql_nulls_not_distinct=False)
    op.alter_column('shows', 'poster_url',
               existing_type=sa.String(length=500),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('shows', 'title',
               existing_type=sa.String(length=300),
               type_=sa.VARCHAR(length=255),
               existing_nullable=False)
    op.add_column('reddit_posts', sa.Column('num_comments', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.drop_index(op.f('ix_reddit_posts_show_id'), table_name='reddit_posts')
    op.drop_index(op.f('ix_reddit_posts_created_utc'), table_name='reddit_posts')
    op.create_index('ix_reddit_posts_subreddit', 'reddit_posts', ['subreddit'], unique=False)
    op.alter_column('reddit_posts', 'subreddit',
               existing_type=sa.String(length=200),
               type_=sa.VARCHAR(length=64),
               nullable=False)
    op.alter_column('reddit_posts', 'score',
               existing_type=sa.INTEGER(),
               nullable=False,
               existing_server_default=sa.text('0'))
    op.alter_column('reddit_posts', 'url',
               existing_type=sa.String(length=1000),
               type_=sa.TEXT(),
               nullable=True)
    op.alter_column('reddit_posts', 'title',
               existing_type=sa.String(length=500),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('reddit_posts', 'reddit_id',
               existing_type=sa.String(length=32),
               type_=sa.VARCHAR(length=20),
               nullable=False)
    op.add_column('not_interested', sa.Column('show_id', sa.INTEGER(), autoincrement=False, nullable=False))
    op.add_column('not_interested', sa.Column('reason', sa.TEXT(), autoincrement=False, nullable=True))
    op.drop_constraint(None, 'not_interested', type_='foreignkey')
    op.create_foreign_key('not_interested_user_id_fkey', 'not_interested', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('not_interested_show_id_fkey', 'not_interested', 'shows', ['show_id'], ['show_id'], ondelete='CASCADE')
    op.drop_constraint('uq_not_interested_user_tmdb', 'not_interested', type_='unique')
    op.drop_index(op.f('ix_not_interested_tmdb_id'), table_name='not_interested')
    op.create_unique_constraint('uq_not_interested_user_show', 'not_interested', ['user_id', 'show_id'], postgresql_nulls_not_distinct=False)
    op.create_index('ix_not_interested_show_id', 'not_interested', ['show_id'], unique=False)
    op.drop_column('not_interested', 'tmdb_id')
    op.execute("ALTER TABLE auth_users DROP CONSTRAINT IF EXISTS uq_auth_users_email")
    op.alter_column('auth_users', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.drop_column('auth_users', 'username')
    op.create_table('users',
    sa.Column('id', sa.INTEGER(), server_default=sa.text("nextval('users_id_seq'::regclass)"), autoincrement=True, nullable=False),
    sa.Column('username', sa.VARCHAR(length=64), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name='users_pkey'),
    sa.UniqueConstraint('username', name='users_username_key', postgresql_include=[], postgresql_nulls_not_distinct=False),
    postgresql_ignore_search_path=False
    )
    op.create_index('ix_users_id', 'users', ['id'], unique=False)
    op.create_table('rec_feedback',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('show_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('useful', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name='rec_feedback_pkey')
    )
    op.create_index('ix_rec_feedback_user_id', 'rec_feedback', ['user_id'], unique=False)
    op.create_index('ix_rec_feedback_show_id', 'rec_feedback', ['show_id'], unique=False)
    op.create_index('ix_rec_feedback_id', 'rec_feedback', ['id'], unique=False)
    op.create_table('recommendation_log',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('show_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('score', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('components_json', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['show_id'], ['shows.show_id'], name='recommendation_log_show_id_fkey', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='recommendation_log_user_id_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='recommendation_log_pkey')
    )
    op.create_index('ix_recommendation_log_user_id', 'recommendation_log', ['user_id'], unique=False)
    op.create_index('ix_recommendation_log_show_id', 'recommendation_log', ['show_id'], unique=False)
    op.create_table('recommendation_feedback',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('show_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('useful', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['show_id'], ['shows.show_id'], name='recommendation_feedback_show_id_fkey', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='recommendation_feedback_user_id_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='recommendation_feedback_pkey'),
    sa.UniqueConstraint('user_id', 'show_id', name='uq_feedback_user_show', postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_index('ix_recommendation_feedback_user_id', 'recommendation_feedback', ['user_id'], unique=False)
    op.create_index('ix_recommendation_feedback_show_id', 'recommendation_feedback', ['show_id'], unique=False)
    op.create_table('favorites_tmdb',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('tmdb_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='favorites_tmdb_user_id_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='favorites_tmdb_pkey'),
    sa.UniqueConstraint('user_id', 'tmdb_id', name='uq_user_tmdb', postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_index('ix_favorites_tmdb_user_id', 'favorites_tmdb', ['user_id'], unique=False)
    op.create_index('ix_favorites_tmdb_tmdb_id', 'favorites_tmdb', ['tmdb_id'], unique=False)
    op.create_table('user_rating',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('tmdb_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('title', sa.VARCHAR(length=300), autoincrement=False, nullable=True),
    sa.Column('rating', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('watched_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('seasons_completed', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('notes', sa.VARCHAR(length=1000), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='user_rating_user_id_fkey', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='user_rating_pkey'),
    sa.UniqueConstraint('user_id', 'tmdb_id', name='uq_rating_user_show', postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_index('ix_user_rating_user_id', 'user_rating', ['user_id'], unique=False)
    op.create_index('ix_user_rating_tmdb_id', 'user_rating', ['tmdb_id'], unique=False)
    # ### end Alembic commands ###
