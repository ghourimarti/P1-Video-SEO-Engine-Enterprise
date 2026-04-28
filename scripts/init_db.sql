-- Runs once on Postgres container first start via docker-entrypoint-initdb.d/
-- M2 will run Alembic migrations on top of this baseline.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for BM25-style text search

-- Anime documents table
CREATE TABLE IF NOT EXISTS anime_documents (
    id          SERIAL PRIMARY KEY,
    mal_id      INTEGER UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    score       FLOAT,
    genres      TEXT[],
    synopsis    TEXT NOT NULL,
    -- dense embedding (text-embedding-3-large = 3072 dims)
    embedding   vector(3072),
    -- tsvector for BM25 full-text search
    tsv         TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector('english', coalesce(name, '') || ' ' || coalesce(synopsis, ''))
                ) STORED,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- IVFFlat index for ANN search (M2: tune lists= after data is loaded)
CREATE INDEX IF NOT EXISTS anime_embedding_idx
    ON anime_documents USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- GIN index for full-text search
CREATE INDEX IF NOT EXISTS anime_tsv_idx
    ON anime_documents USING GIN (tsv);

-- Request audit log (M7)
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    request_id  TEXT NOT NULL,
    user_id     TEXT,
    query_hash  TEXT NOT NULL,  -- SHA-256 of the raw query (PII-free)
    model_used  TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd    FLOAT,
    cached      BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audit_log_user_idx ON audit_log (user_id, created_at DESC);
