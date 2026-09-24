SET LOCAL statement_timeout = '750s';

CREATE INDEX index_chunks_vector_t12 ON reposcope.index_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m=64, ef_construction=400);

DROP INDEX reposcope.index_chunks_vector;
ALTER INDEX reposcope.index_chunks_vector_t12 RENAME TO index_chunks_vector;

SET LOCAL statement_timeout = '30s';
