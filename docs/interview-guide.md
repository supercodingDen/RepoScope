# RepoScope technical walkthrough

Use this guide to explain the implemented system and its limits. Demonstrate the [pinned small-repository walkthrough](demo.md) first; use the [status record](project-status.md) to distinguish executed checks from planned work.

1. **Why an outbox?** Import/run admission and outbox insertion share one PostgreSQL transaction. Publishing occurs afterward and waits for a JetStream acknowledgment before the row is marked published. This prevents a committed job from depending on an uncommitted broker send. Duplicate publication is expected and handled.
2. **Why leases and fencing?** A worker may stop after a message is delivered. Renewable leases permit takeover; the fencing token makes a stale worker's later write fail. Business completion and consumer completion commit together, then the message is acknowledged. External model billing cannot be promised exactly once.
3. **How is source pinned?** The indexer resolves a public GitHub reference once to a commit, streams eligible files without running repository code, records skipped files, and publishes only a complete generation. Searches and agent runs use that generation; citations include the commit and exact path/line span.
4. **How is load bounded?** Shared admission, per-role worker limits, bounded embedding batches, database pools, deadlines, source quotas, context/tool limits, and budget reservations constrain work at distinct boundaries. Private metrics report backlog and failure rather than putting IDs or paths into labels.
5. **How does retrieval work?** Scoped HNSW vector and full-text branches feed deterministic reciprocal-rank fusion. T12 compared HNSW to exact neighbors on 100,029 real chunks. The shipped setting achieved 0.9235 mock-vector Recall@10 and approximately 80 QPS at 32 active clients, but 438–445 ms p95 missed the 100-ms target. ANN recall is not answer relevance; no human-reviewed semantic score is claimed.
6. **What happens when dependencies fail?** PostgreSQL is authoritative, NATS delivery is recoverable from the outbox, and Redis state is disposable. The [fault matrix](t10-operations.md) and [recovery guide](failure-modes.md) state observed local behavior. The hosted backup/restore and rollback proof are still open.
7. **What is the security boundary?** The local API binds loopback, business routes require a bearer token, other service ports are private, and imported code is never executed. The [T11 review](t11-security.md) records scan results and unresolved image advisories. TLS, domain, host firewall, and off-host backups are T15 work.

Avoid describing RepoScope as highly available, production deployed, semantically validated, or fully meeting the PDF's performance targets. A measured improvement is defensible only with its workload, baseline, raw measurements, and caveats from the [performance report](t12-performance.md).

## Five-minute reviewer path

Use the [local demo](demo.md) only after the stack is already ready. In the first minute, show a pinned public repository import and explain that HTTP 202 is backed by one database transaction containing job and outbox event. In the second minute, show worker progress and describe lease fencing and a complete index generation. In the third, perform scoped hybrid search and inspect a path/line/commit citation. In the fourth, submit a read-only agent run and reconnect to SSE with `Last-Event-ID`. In the fifth, show the [fault matrix](t10-operations.md), [raw T12 measurements](t12-performance.md), and [acceptance ledger](acceptance.md), naming the remaining public-host and performance gates. Cold builds and source acquisition are outside a guaranteed five-minute duration.

## Truthful English resume bullets

**SWE version**

- Built RepoScope, a Python/FastAPI code-intelligence service with asynchronous repository ingestion, PostgreSQL transactional outbox, NATS JetStream workers, fenced leases, idempotent jobs, and resumable SSE events.
- Implemented immutable Git revision pinning, bounded source acquisition, AST-aware Python/TypeScript chunking, hybrid pgvector/full-text retrieval, and file/line/commit citations without executing ingested code.
- Benchmarked 100,029 real code chunks and 200 fixed queries; measured ~80 QPS at 32 active search clients and Recall@10 of 0.9235 against exact mock-vector neighbors while documenting the unmet 100-ms p95 target.

**AI/ML version**

- Designed a retrieval-augmented code agent with three read-only tools, scoped evidence, one-hop dependency expansion, token budgets, immutable citations, and persisted event replay.
- Implemented batched 384-dimensional embedding pipelines with provenance and generation isolation; compared exact and HNSW neighbors plus full-text fusion on 100,029 real code chunks and 200 fixed queries.
- Added explicit model routing and atomic spend reservations, with mock-by-default execution and live-provider costs gated by verified prices and operator opt-in; reported mock-vector recall separately from unmeasured semantic answer quality.

These bullets describe source/local evidence, not a public production deployment. Update them only after the open [acceptance gates](acceptance.md) have actual proof.
