# Requirement traceability

The source is the user's 25-page RepoScope design PDF, the original 16-task roadmap, and the latest T01 instruction. T01 defines the following requirements; it does not claim their runtime implementation is complete.

| ID | Requirement | T01 artifact | Runtime acceptance owner |
| --- | --- | --- | --- |
| R01 | Public repo submission and 202 async job | public.yaml; RepositoryCreate/Accepted | T03 |
| R02 | Durable messaging and independent workers | ADR-001; architecture.md | T04 |
| R03 | Transactional outbox and idempotent consumer | ADR-003; contracts.md | T03-T04 |
| R04 | Bounded parallelism and backpressure | spec.md resource table | T04/T10 |
| R05 | Real source, content hashes, provenance | spec.md; Citation | T05-T06 |
| R06 | AST parsing and one-hop dependency expansion | ADR-005; spec.md | T06-T08 |
| R07 | Batch embeddings and memory bounds | spec.md; pyproject.toml | T06 |
| R08 | At least 100K real code chunks | roadmap.md; benchmark contract | T12 |
| R09 | Exact/HNSW/FTS/RRF retrieval | ADR-002; SearchRequest/Response | T07/T12 |
| R10 | Fixed 200+ query set and recall/QPS/p95 | roadmap.md; evaluation policy | T12 |
| R11 | Three read-only agent tools | tools/*.schema.json | T08 |
| R12 | Source path, line, commit citations | Citation; RunResult | T07-T09 |
| R13 | Async run and resumable SSE | public.yaml; RunEvent; contracts.md | T09 |
| R14 | Logging/metrics/correlation | AGENTS.md; internal.yaml | T02/T10 |
| R15 | Timeout, graceful shutdown, retries, failures | contracts.md; threat-model.md | T04/T10 |
| R16 | Worker, DB, NATS, provider fault matrix | roadmap.md; ADR-003 | T10 |
| R17 | Two measured optimizations; raw before/after | roadmap.md | T12 |
| R18 | English README, docs, ADRs, diagrams | README.md; AGENTS.md; docs/ | T01/T13 |
| R19 | Compose from a fresh clone | dependencies.md; roadmap.md | T02/T13 |
| R20 | Automated tests, typing, lint, build CI | pyproject.toml; validation scripts | T01/T02 |
| R21 | License and contribution/security policy | CONTRIBUTING.md; threat-model.md | T13 |
| R22 | Actual public GitHub and green CI | roadmap.md; project-status.md | T14 |
| R23 | Live HTTPS, persistence, backup/restore | architecture.md; threat-model.md | T15 |
| R24 | Five-minute demo and truthful resume bullets | roadmap.md | T16 |
| R25 | Strict complete Python types, no TS any | AGENTS.md; mypy config | Every task |
| R26 | Central exceptions and standard HTTP errors | Problem; contracts.md | T02-T03 |
| R27 | Controller/service/repository separation | architecture.md | Every task |
| R28 | Async I/O, streamed files, bounded CPU work | spec.md; AGENTS.md | T02/T05-T08 |
| R29 | Mainstream pinned dependencies before code | pyproject.toml; uv.lock; dependencies.md | T01/T02 |
| R30 | Credentials never published | ignore rules; blank env template; threat model | Every task |
| R31 | Luna preferred, conditional routing | model-policy.md; model-policy.json | T08 |
| R32 | Avoid whole-repo context and control spend | spec.md; model-policy.md | T06/T08/T10 |

## Explicit changes to the initial plan

| Initial recommendation | T01 decision | Reason |
| --- | --- | --- |
| Go public API | FastAPI/Python API | User delegated choice; reduce solo implementation overhead |
| Private Python retrieval HTTP | Shared in-process service | One implementation across API and agent |
| Local sentence-transformers | OpenAI text-embedding-3-small, explicit 384 dimensions | Latest user pipeline; lower local runtime burden |
| Agents SDK | AsyncOpenAI with a bounded typed loop | One owner for retries, routing, and budgets |
| Simple chunking | Python/TS AST-aware plus explicit fallback | Better source structure without promising universal parsing |
| 80/18/2 model diagram | Luna-first conditional policy | Avoid purposeless expensive calls |
| Python 3.13 initial baseline | Verified local Python 3.12.14; supported range <3.14 | Reproducible tested interpreter; container parity checked in T02 |
| Full frontend | Deferred optional typed client | Preserve core delivery time |
