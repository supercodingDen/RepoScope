# RepoScope v1 specification

Status: T01 contract baseline, 2026-09-16. The user authorized execution of T01 and delegated the final architecture choice. This specification supersedes conflicting Go and local-embedding choices in the earlier roadmap; all reliability and final-delivery requirements remain.

## Product outcome

A developer submits a public GitHub repository, obtains an asynchronous indexing job, searches a complete indexed revision, and asks a read-only agent to explain implementation locations or likely files involved in a reported issue. Answers link to immutable revisions and bounded file ranges. Unsupported questions produce an explicit insufficient-evidence answer.

## Required v1 behavior

1. Accept a canonical public GitHub HTTPS repository URL and an optional reference, default HEAD. Persist the request, job, idempotency result, and outbox event together.
2. Resolve the requested reference to a commit once in the worker and persist it using compare-and-set before indexing. Redelivery reuses that commit. Do not silently re-resolve a moving branch during retry.
3. Safely acquire the source without executing its code. Parse Python and TypeScript/TSX with pinned Tree-sitter grammars. JavaScript, Go, documentation, and other eligible text initially use the explicitly labeled token/line fallback. Language labels do not imply AST support.
4. Chunk at AST boundaries where possible, splitting oversized nodes by token and source-line boundaries. Target 600 tokens, maximum 800 including metadata, overlap at most 80. Retain byte/line spans, symbol/import metadata, parser revision, tokenizer encoding, and content hashes.
5. Use text-embedding-3-small with explicit dimensions=384 and cl100k_base token counting. Queries and chunks must share provider, model, dimensions, normalization, and embedding-space version. Mock vectors are tagged mock and never included in quality/scale claims.
6. Persist batches in an isolated index generation. Publish the active generation only when all eligible files are processed, all required embeddings exist, and the owning fenced attempt still owns the current requested generation. Skipped files and parse fallbacks are counted and reported.
7. Search the active complete generation using scoped vector top-50, FTS top-50, RRF with k=60, and return at most 20 matches, default 10. An empty ready index is valid; an absent ready index returns INDEX_NOT_READY.
8. Agent runs pin a complete generation at submission. The tools are search_code, get_file, and get_repository_summary. Server-side run scope overrides or rejects model-supplied scope. The agent cannot request arbitrary repository IDs or remote URLs.
9. Expand context through at most one hop of statically resolved same-repository imports/references, at most four extra chunks. This is best-effort syntax-based dependency discovery, not a complete semantic call graph. Dynamic imports remain unresolved. No graph expansion through installed third-party packages.
10. Route to Luna by default. A budget-authorized policy may use Terra after evidence has been expanded and a valid complex question still fails the evaluation gate. Sol is explicitly enabled only for a selected expert run. Never upgrade on authentication failures, rate limits, or missing evidence alone.
11. Persist a final structured result and ordered SSE events. Progress is step/status output, not hidden chain-of-thought. SSE supports cursor replay, heartbeats, and bounded buffers.
12. Complete the original 100K real-chunk benchmark, fault matrix, documentation, GitHub release, and external deployment gates before final handover.

## Application boundaries

Three deployable roles share one versioned Python package: API, indexer, and agent. Retrieval code is invoked in process by API and agent; there is no separate internal retrieval HTTP service. FastAPI is confined to transport/bootstrap. One SQL migration owner is src/reposcope/infrastructure/db/migrations; workers never run independent migrations.

The optional React/Next.js frontend is outside T01 and not required for core acceptance. The core demo is CLI plus REST/SSE. A frontend must call the authenticated API, never OpenAI or database services directly. There is no Node dependency until a separately authorized frontend task.

## Resource and security defaults

| Control | Initial value |
| --- | --- |
| HTTP request body | 64 KiB |
| Canonical public sources | github.com only; no credentials, arbitrary hosts, or remote local paths |
| File size / eligible files / source bytes | 1 MiB / 20,000 / 250 MiB per import |
| Total temporary disk | 1 GiB per job with enforced quota/monitor |
| Clone / total ingestion deadline | 120 seconds / 30 minutes |
| Indexer / agent / embedding concurrency | 2 / 2 / 2 per process |
| Embedding batch | 32 chunks and at most 20,000 tokens |
| Pending jobs | 100 per deployment; reject further admission with 429 |
| DB pool | API 10; indexer 5; agent 5; total budget 20 connections |
| Query / provider timeout | 10 seconds / 45 seconds |
| Lease / heartbeat | 60 seconds / 15 seconds |
| Ingest handler attempts | At most 5 within the job deadline |
| Agent total deadline | 120 seconds |
| Model attempts / tool steps | At most 6 / 6 across all retries and recovered attempts |
| Per-call model input/output | 24,000 / 2,000 tokens, including tools/history and reasoning output allocation |
| Seed/expanded retrieval content | 8,000 tokens combined; at most 12 chunks |
| Tool result / file range | 4,000 tokens and 12,000 characters / 200 lines |
| Request budget / daily budget / project budget | USD 0.10 / 1.00 / 4.00; live mode disabled initially |
| SSE connections / retention | 2 per principal, 20 total / 24 hours after terminal state |

These are conservative initial limits, not hardware capacity claims. Change them through reviewed configuration and repeat the affected tests. All replicas share atomic DB budget reservations; process-local semaphores alone do not limit total spend.

## Exclusions

No private repositories, code execution, automated pull requests, repository writes, arbitrary web fetch tool, user-defined shell, multi-tenant SaaS/RBAC, Kubernetes, Kafka, service mesh, fine-tuning, or whole-repository model context. No absolute security or availability guarantee is claimed for a single-host demo.
