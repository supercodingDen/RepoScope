ALTER TABLE reposcope.jobs ADD COLUMN index_attempts integer NOT NULL DEFAULT 0
    CHECK (index_attempts BETWEEN 0 AND 5);
ALTER TABLE reposcope.delivery_quarantine DROP CONSTRAINT delivery_quarantine_consumer_check;
ALTER TABLE reposcope.delivery_quarantine ADD CONSTRAINT delivery_quarantine_consumer_check
    CHECK (consumer IN ('indexer','source','agent'));

CREATE TABLE reposcope.index_files (
    generation_id uuid NOT NULL REFERENCES reposcope.index_generations(generation_id),
    path text NOT NULL,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    byte_count integer NOT NULL CHECK (byte_count >= 0),
    language text NOT NULL,
    parse_mode text NOT NULL CHECK (parse_mode IN ('ast','syntax-fallback','language-fallback')),
    pipeline_version text NOT NULL,
    dependencies jsonb NOT NULL CHECK (jsonb_typeof(dependencies) = 'array'),
    chunk_count integer NOT NULL CHECK (chunk_count >= 0),
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(generation_id,path)
);

CREATE TABLE reposcope.index_chunks (
    generation_id uuid NOT NULL,
    path text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    start_byte integer NOT NULL CHECK (start_byte >= 0),
    end_byte integer NOT NULL CHECK (end_byte > start_byte),
    start_line integer NOT NULL CHECK (start_line >= 1),
    end_line integer NOT NULL CHECK (end_line >= start_line),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    token_count integer NOT NULL CHECK (token_count BETWEEN 1 AND 800),
    symbol text,
    chunk_text text NOT NULL,
    embedding vector(384) NOT NULL,
    PRIMARY KEY(generation_id,path,ordinal),
    FOREIGN KEY(generation_id,path) REFERENCES reposcope.index_files(generation_id,path)
);

CREATE INDEX index_chunks_generation ON reposcope.index_chunks(generation_id);
CREATE INDEX index_files_generation ON reposcope.index_files(generation_id);
CREATE INDEX index_chunks_fts ON reposcope.index_chunks
    USING gin (to_tsvector('simple', chunk_text));
CREATE INDEX index_chunks_vector ON reposcope.index_chunks
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE reposcope.embedding_cache (
    space_version text NOT NULL,
    input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[a-f0-9]{64}$'),
    embedding vector(384) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(space_version,input_sha256)
);

CREATE TABLE reposcope.embedding_reservations (
    reservation_id uuid PRIMARY KEY,
    budget_day date NOT NULL,
    provider text NOT NULL CHECK (provider = 'openai'),
    model text NOT NULL CHECK (model = 'text-embedding-3-small'),
    requested_tokens integer NOT NULL CHECK (requested_tokens BETWEEN 1 AND 20000),
    reserved_usd numeric(18,9) NOT NULL CHECK (reserved_usd > 0),
    actual_tokens integer CHECK (actual_tokens >= 0),
    state text NOT NULL CHECK (state IN ('reserved','settled','uncertain')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX embedding_reservations_budget ON reposcope.embedding_reservations(budget_day,state);
