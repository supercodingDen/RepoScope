# Project status

Milestone: **T08 pinned read-only agent implemented and verified in the native Windows environment**.
Verification date: 2026-09-23 UTC. Working project: `D:\RepoScope_project\reposcope`.

## T08 delivery and verification

- The agent consumer verifies the persisted lease and ready/superseded completed generation, retrieves bounded evidence from that exact commit, and exposes only search, verified file-range read, and repository-summary tools. All model-supplied scope IDs are checked against the admitted run.
- Default mock mode completes runs with a cited source excerpt or an insufficient-evidence result and makes no paid calls. Live Luna uses the official Responses SDK with local function tools and a structured final answer. Terra and Sol remain disabled.
- Migration `0006_agent` adds durable per-attempt reservations and usage state. Every paid attempt reserves under the shared admission lock before dispatch. The model loop limits attempts and tool steps to six, input estimates to 24K tokens, output to 2K tokens, and respects the original run deadline. Timeout/unknown usage stays reserved.
- Real PostgreSQL tests exercised fixed-version retrieval after supersession, mock completion and persistence, a simulated Luna reservation-before-call and usage settlement, stale prices, uncertain costs, and the seventh-attempt rejection. No live paid call was made. See [T08 guide](t08-agent.md).

| T08 check | Executed result |
| --- | --- |
| Full offline pytest | 339 passed, 74 skipped |
| Native PostgreSQL/NATS/public GitHub integration | 77 passed, 1 optional benchmark skipped |
| Strict mypy, Ruff lint/format | Windows and Linux targets passed; 101 Python files type-checked, 138 formatted |
| Contracts | 48 exports current; 20 schema/example pairs and 2 OpenAPI documents validated |
| Independent review | Cumulative evidence, retry cost, clipped line range and startup configuration findings fixed and retested |
| Redacted source-only Gitleaks | Final scan recorded in [T08 checks](verification/t08-checks.txt) |

## T07 delivery and verification

- Authenticated `POST /v1/search` resolves only the caller's active ready generation and pins its commit, embedding space and source citations. Unknown or foreign repositories are hidden; unfinished indexes return `INDEX_NOT_READY`; empty ready indexes return no matches without an embedding call.
- Query embedding uses the indexed 384-dimensional space. Vector and code-friendly `simple` FTS searches each retrieve at most 50 candidates with identical generation, language and literal path-prefix filters. Underfilled global ANN searches fall back to scoped exact top-50. RRF `k=60` breaks ties by path and ordinal. A bounded exact-vector path supplies a baseline; public search uses the HNSW-eligible path. Deterministic chunk UUIDs preserve distinct locations for repeated content.
- The API shares the durable paid-call budget controls with the indexer when explicitly configured for live embeddings. Default mock mode made zero paid calls. Agent execution and one-hop context expansion are later work.

| T07 check | Executed result |
| --- | --- |
| Full offline pytest | 333 passed, 71 skipped |
| Native PostgreSQL/NATS/public GitHub integration | 74 passed, 1 optional benchmark skipped in 80.56 s |
| Strict mypy, Ruff lint/format | Passed; 95 Python files type-checked on Windows and Linux targets; 129 files formatted |
| Initial 1,009-real-chunk retrieval baseline | Exact DB p95 94.199 ms; HNSW-eligible DB p95 98.325 ms; end-to-end mock text p95 93.866 ms; 3 × 20 serial queries after warm-up |
| Independent review | [Filtered ANN underfill fixed and closure reviewed](verification/t07-review.md); no remaining Critical or Important finding |
| Redacted source-only Gitleaks | 207 reviewed files, approximately 1.11 MB; no leaks found |

The baseline used 16 distinct CPython 3.12.14 files, source fingerprint `11bc66078fab0e384f590b0811ff659872049a71f0d791bea5df4381267f887b`. The small corpus may use sequential scans, so it does not demonstrate HNSW index use or meet the roadmap's 100K/32-client gate. It measures mock query embeddings, not live-provider latency or semantic relevance. The [T07 guide](t07-retrieval.md) and [check evidence](verification/t07-checks.txt) record the method and remaining gates. Docker/Compose acceptance remains open below.

## T06 delivery and verification

- A third durable source-continuation consumer turns verified T05 blobs into AST-aware or labeled-fallback chunks with exact byte/line citations. Its index attempts are independent of source-acquisition attempts.
- Migration `0005_index` adds per-file fenced checkpoints, 384-dimensional vectors, full-text/HNSW indexes, versioned vector reuse and durable paid-call reservations. A final transaction publishes a complete ready generation, job and active pointer together; superseded generations do not take over.
- Default mock embeddings are deterministic and incur no provider cost. A live adapter is available only with an explicit key, paid opt-in, current operator-supplied price and UTC daily ceiling. No live provider call or quality evaluation was executed.
- Real PostgreSQL/NATS tests cover duplicate-content citations, replay, stale fences, fifth source attempt, supersession, empty generations and budget accounting. The full native integration suite and offline suite pass. The 10K/50K benchmark parsed distinct files from version-pinned CPython 3.12.14 and locked public package code in one pass, without replay or generated content. It measures parsing/embedding memory and vector cardinality, not a 50K-row database load.

| T06 check | Executed result |
| --- | --- |
| Local pytest, including opt-in skips | 324 passed, 67 skipped |
| Isolated PostgreSQL 17/pgvector 0.8.6, NATS 2.14.7 and real public GitHub source | 64 passed in 58.60 s |
| Strict mypy, Ruff lint and formatting | Passed; 87 Python files type-checked for Windows and Linux targets, 117 files formatted |
| Contract exports and semantic validation | 48 current files; 20 schema/example pairs and 2 OpenAPI documents valid |
| Redacted source-only Gitleaks | 194 reviewed files, approximately 1.06 MB scanned; no leaks found |
| Independent review | [All Important findings fixed](verification/t06-review.md) and closure reviewed; no remaining Critical or Important finding |

| T06 native scale gate | Actual chunks/vectors | Files | Time | Peak process working set |
| --- | ---: | ---: | ---: | ---: |
| 10K | 10,012 / 10,012 | 332 | 21.437 s | 156,184,576 bytes |
| 50K | 50,007 / 50,007 | 1,705 | 112.125 s | 184,516,608 bytes |

The scale input comprised 4,804 eligible files; the checked source fingerprint was `159dcd550b7f2ec53802f11c65859d7bcab5eba082a8eb21a5a19119aa515c86`. Peak traced Python allocations were 21,253,086 and 26,400,487 bytes respectively. The benchmark made no provider request. [Machine-readable scale evidence](verification/t06-scale.json) records the measurements. Database cardinality is verified on smaller real-PostgreSQL end-to-end fixtures; a 50K-row PostgreSQL/HNSW ingestion run remains unexecuted.

Usage: [T06 indexing](t06-indexing.md). The older T04/T05 evidence below remains as the historical acceptance record.

## Delivered

- T04: transactional outbox publication, bounded durable JetStream consumers, renewable fenced leases, durable retries, completion-before-ACK, safe quarantine and stalled-work reconciliation.
- T05: canonical public GitHub admission, immutable commit pinning, isolated blobless Git acquisition, controlled public-IP transport and download accounting, file/path/secret exclusions, process-tree termination and bounded storage.
- Deterministic source manifests and scoped durable `repo.source.acquired` continuations committed atomically with source-stage completion. T06 now consumes this staged handoff.
- Operator-only local snapshot CLI, authoritative obsolete/terminal cleanup, transient cleanup recovery and safe finalization rollback.
- Additive migrations0003/0004, exported contracts, runtime configuration, source volume/indexer egress, pinned Git/CA dependencies and smoke-test updates.

Usage: [durable delivery](t04-delivery.md), [source acquisition and local import](t05-acquisition.md), [existing HTTP API](t03-api.md). Scope proof: [acceptance ledger](plans/2026-09-22-t04-t05-acceptance.md).

## T04/T05 executed verification

| Check | Actual result |
| --- | --- |
| Offline pytest |305 passed;57 opt-in dependency/Git cases skipped |
| Real PostgreSQL17.11 + pgvector0.8.6, NATS2.14.7 and public GitHub |61 passed in58.96s; explicitly covers the opt-in cases |
| NATS stop/restart recovery |1 passed separately in5.19s |
| Strict mypy |75 files passed for Windows and Linux targets |
| Ruff lint / format |Passed;100 files formatted |
| Contract exports / validation |48 current files;20 schema/example pairs and2 OpenAPI documents passed |
| Python compilation / Compose parsing |Passed; neither is a container build |
| Source-only redacted Gitleaks |Passed; local secrets/imported source excluded |
| Independent final review |Three reproduced findings fixed and approved;37 focused tests independently rerun |

Counts overlap and must not be added as a unique-test total. Evidence: [quality checks](verification/t04-t05-checks.txt), [native/public checks](verification/t04-t05-native-checks.txt), [security scan](verification/t04-t05-security-checks.txt), [review](verification/t04-t05-review.md). Fault-injection tests deliberately emit safe failure/retry logs. No paid provider call occurred.

Actual public sample: `https://github.com/pallets/itsdangerous`, commit `672971d66a2ef9f85151e53283113f33d642dabd`,49 eligible files. Repeated pinned acquisition produced manifest SHA256 `7fb39a96d85f32060b90849bc4da4dca84e109bdc5e9f6d9d06a4a4521257ebb`. Provenance lives in `bench/data/repositories.json`; source content is not redistributed. Automatic license identification remains `unknown` with license-file hashes retained.

Native checks used isolated temporary localhost databases/brokers and the verified portable Git binary. The Windows pgvector binary is the previously documented unofficial0.8.6_17 release; this does not validate the Linux image. Temporary servers were stopped afterward; no system service was installed.

## Open container acceptance

Docker and a usable WSL backend are unavailable. The prior T02 Linux image build, full Compose role/network/dependency-outage smoke, container shutdown and persistent-volume acceptance remain **unexecuted**. Native success and Linux-target typing do not close this gate. Container Git differs from the tested Windows MinGit. Once a Docker environment is available, run `uv run --frozen python scripts/smoke_test.py`; it uses isolated temporary credentials and does not read the developer dotenv file.

Disk limits are enforced by monitoring and finalization checks, with possible transient physical overshoot. Download accounting bounds application-forwarded TLS transport payload; kernel receive buffers are outside that quota. Local imports require a trusted quiescent operator root. These are bounded source controls, not an absolute hostile-host isolation claim.

## Next milestone

T08: pinned read-only agent execution using the shared retrieval service. T09's one-hop context expansion and later performance gates remain open. The original overall job deadline still applies to source acquisition and indexing.

The reviewed source is synchronized to the owner's private GitHub repository, `supercodingDen/RepoScope`, after each complete task. The D-drive extraction has no persistent local Git history; synchronization uses the connected GitHub integration. Public release, PR, hosted deployment and system installation were not performed. Remote CI results have not been verified. Earlier T03 evidence remains in `docs/verification/t03-checks.txt`, `t03-native-checks.txt` and the T03 API guide.
