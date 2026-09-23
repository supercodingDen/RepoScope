# T07 scoped retrieval

After an indexing job reaches `succeeded`, send an authenticated `POST /v1/search` request:

```json
{"repository_id":"00000000-0000-0000-0000-000000000001","query":"Where is authentication checked?","top_k":10,"language":"python","path_prefix":"src"}
```

Use the repository ID returned by `POST /v1/repositories`. `language` and `path_prefix` are optional; `top_k` defaults to 10 and is capped at 20. The path prefix matches a complete file path or descendants of a directory, treating `%` and `_` literally. The bearer principal is always taken from the server's configuration, never the request. Unknown or foreign repositories return `NOT_FOUND`; a repository without an active ready generation returns `INDEX_NOT_READY`; an empty ready generation returns an empty result.

Results carry the immutable commit SHA, generation ID, source path and line range. A chunk ID is deterministic for the generation, path and ordinal. Searches pin the active generation before computing the query vector, so an index publication during the query cannot mix revisions. Vector and `simple` full-text searches each return at most 50 scoped candidates; when global ANN filtering underfills, a scoped exact query supplies the vector top-50. Reciprocal-rank fusion uses `k=60` and a deterministic path/ordinal tie-break. An exact-vector path also exists for measurement and filtered recall checks. The service is in-process and available to the future agent workflow; T08 does not yet execute it.

The API uses the same embedding-space version as the indexer. Mock mode remains the default and makes no provider call. For live query embeddings, the API and indexer both need the same explicit `PROVIDER_MODE=openai`, paid opt-in, key, verified price and daily budget settings. Query calls use the same durable budget ledger as indexing. A query over 800 `cl100k_base` tokens is rejected. No live provider call was made during T07 verification.

The initial native baseline used 1,009 chunks from 16 distinct CPython 3.12.14 standard-library files; source fingerprint `11bc66078fab0e384f590b0811ff659872049a71f0d791bea5df4381267f887b`. After five warm-ups, three trials of 20 serial searches measured p95 of 94.199 ms for exact database search, 98.325 ms for the HNSW-eligible database path, and 93.866 ms for end-to-end mock text search. The database-path numbers include FTS and application-to-database round trips. The small corpus may cause PostgreSQL to choose a sequential scan for the HNSW-eligible query; these figures are a smoke baseline, not a 100K-chunk/32-client target result or a real-embedding relevance measure. The opt-in reproducible test is `tests/integration/test_retrieval_scale.py` with `T07_BENCH_SOURCE_ROOT` pointing at a verified public CPython 3.12.14 `Lib` tree.

Docker/Compose acceptance, a 100K real-chunk load, filtered ANN recall and live-query latency remain open. See [project status](project-status.md).
