"""001: initial schema — anime_documents + audit_log.

Revision ID: 001
Revises: —
Create Date: 2026-04-28

Note: pgvector and pg_trgm extensions are created by init_db.sql
(Docker entrypoint) or must be created manually with superuser
privileges before running this migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Custom type for vector — raw DDL since SQLAlchemy has no native vector type
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("""
        CREATE TABLE IF NOT EXISTS anime_documents (
            id          SERIAL PRIMARY KEY,
            mal_id      INTEGER UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            score       FLOAT,
            genres      TEXT[],
            synopsis    TEXT NOT NULL,
            embedding   vector(3072),
            tsv         TSVECTOR GENERATED ALWAYS AS (
                            to_tsvector('english', coalesce(name, '') || ' ' || coalesce(synopsis, ''))
                        ) STORED,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS anime_embedding_idx
            ON anime_documents USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 50)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS anime_tsv_idx
            ON anime_documents USING GIN (tsv)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id            BIGSERIAL PRIMARY KEY,
            request_id    TEXT NOT NULL,
            user_id       TEXT,
            query_hash    TEXT NOT NULL,
            model_used    TEXT,
            input_tokens  INTEGER,
            output_tokens INTEGER,
            cost_usd      FLOAT,
            cached        BOOLEAN DEFAULT FALSE,
            created_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS audit_log_user_idx
            ON audit_log (user_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS anime_documents")
