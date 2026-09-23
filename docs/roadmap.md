# Revised delivery roadmap

The original T01-T16 task IDs are preserved. ADR-004 and ADR-005 replace conflicting language, internal transport, embedding, and agent SDK details. All performance, recovery, security, GitHub, and hosted deployment gates remain.

| Task | Deliverable and gate |
| --- | --- |
| T01 | Specification, typed contracts, model policy, dependencies, threat model, ADRs, verification evidence |
| T02 | FastAPI and two worker entry points; Compose; health/readiness; CI; reproducible image pins |
| T03 | SQL migrations, jobs/runs, idempotency, budgets, business-plus-outbox transaction |
| T04 | JetStream consumers/publisher, fenced leases, bounded retries, reconciliation, crash-gap tests |
| T05 | Safe public source acquisition, immutable revision pinning, URL/path and resource controls |
| T06 | AST-aware chunks, dependency metadata, embedding batches, source blobs, isolated generations |
| T07 | Shared retrieval service, exact/FTS/HNSW/RRF, filters, citations, initial benchmark |
| T08 | Read-only tools, official SDK adapter, Luna-first bounded loop and cost reservations |
| T09 | Persisted run events, resumable SSE, import-to-answer CLI demonstration |
| T10 | Metrics/logging, admission/backpressure, dependency outages, crash recovery fault matrix |
| T11 | Public access, image/dependency/secret scans, endpoint and resource security review |
| T12 | 100K real chunks, 200+ fixed queries, two measured improvements, raw before/after results |
| T13 | Final English README, architecture, ADRs, Apache-2.0 release license/notices, contribution/security/docs |
| T14 | Owner-confirmed GitHub repository, publication, remote CI, versioned release |
| T15 | Owner-selected funded host, HTTPS deployment, restart persistence, actual backup/restore/rollback |
| T16 | Requirement evidence matrix, demonstration, operating handover, truthful English resume bullets |

## Performance targets retained from the PDF

Reference environment: 8 vCPU, 16 GiB RAM, SSD, Linux Docker; actual hardware/software always recorded. At least 100K real source chunks, 32 concurrent searches for 60-120 seconds, search throughput at least 50 QPS, search p95 at most 100 ms, DB vector p95 at most 75 ms, Recall@10 against exact at least 0.90, non-search endpoint p95 at most 30 ms, orchestration overhead below 300 ms, no OOM, and no duplicate committed results in forced-redelivery tests.

These remain goals, not measured claims. Remote query embeddings can materially increase end-to-end text-search latency. Report DB-only, cached/precomputed-query HTTP search, live text search including query embeddings, and full agent latency separately. Do not label the cached profile as ordinary cold text-search performance. A missed target remains open until optimized or explicitly revised with the user.

Compare exact versus HNSW and sweep ef_search=40/80/120/200. Hold corpus, model, query set, filters, hardware, and cache state constant. Measure worker concurrency and batch-size trade-offs. Preserve raw results for at least three measured trials after warm-up. ANN Recall@10 is not a substitute for semantic answer relevance; retain a separately reviewed code-question evaluation set.

## Deferred decisions

GitHub account/remote and host/budget cannot be inferred from the project name. Do not create or publish to an arbitrary account. T01 chooses the proposed name reposcope and a single-owner authenticated demo, but does not purchase hosting or assert the user's approval of a particular recurring bill. Those decisions are required before T14/T15, not before local skeleton work.
