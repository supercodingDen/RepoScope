# ADR-002: Keep vectors and transactional state in PostgreSQL

Status: accepted for v1. Date: 2026-09-16.

Store source metadata, jobs, runs, outbox, generations, and vectors together in PostgreSQL with pgvector. Use B-tree scope/path indexes, GIN full-text indexes, exact cosine ground truth, and HNSW approximate retrieval. A dedicated vector database would add an operating dependency and cross-store consistency work at the initial 100K-chunk scale.

The first live embedding space is text-embedding-3-small, explicitly 384 dimensions. HNSW tuning reports recall and latency together. Filtered ANN can return too few candidates; evaluate iterative scans or a bounded exact fallback within the same generation. Do not compare hybrid relevance with vector ANN recall as if they measure the same thing.

Consequence: vector and transactional workloads share resource budgets. Measure connection, CPU, I/O, and memory contention. Separate retrieval storage only when measured load or filtering requirements justify it.

Reference: [pgvector documentation](https://github.com/pgvector/pgvector).
