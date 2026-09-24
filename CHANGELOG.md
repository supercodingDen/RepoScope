# Changelog

## [Unreleased]

T15 hosting and T16 final acceptance are not included in v0.1.0. The T12 search-latency, non-search HTTP, semantic-quality, live-provider, and single-job 100K ingestion gates remain open.

## [0.1.0] - 2026-09-24

Initial pre-release candidate: a Python API, indexer, and read-only agent with PostgreSQL/pgvector, NATS JetStream, and Redis; durable jobs, transactional outbox, leases/fencing, bounded admission and budgets, pinned public-source indexing, scoped hybrid search, source citations, and replayable SSE. The repository includes an isolated mock-only demo, contract/quality/security checks, Apache-2.0 licensing, and raw T12 benchmark evidence.

The release is not a hosted service. Its mock provider does not establish semantic answer quality. T12 measured 100,029 real source-located chunks and 200 fixed questions; the shipped 32-client profile reached about 80 QPS and mock-vector Recall@10 0.9235, but search p95 of 438–445 ms missed the 100-ms target. See [project status](docs/project-status.md) and [performance evidence](docs/t12-performance.md).
