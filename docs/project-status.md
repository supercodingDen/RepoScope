# Project status

Milestone: **T15/T16 source handover prepared; GitHub publication audit in progress; actual hosted/public and remaining T12 acceptance gates remain open**.
Verification date: 2026-10-22 publication review; previous T15/T16 source checks: 2026-09-28. Working project: `D:\RepoScope_project\reposcope`.

## Public-repository preparation and remaining gate

- The existing GitHub repository remains **private**. [Publication readiness](publication-readiness.md) records a 13-branch tree audit, a redacted review of retrievable Actions logs, an in-memory inspection of the tracked benchmark ZIP, and the remaining historical and release-asset audit limits. The owner accepted that existing author email metadata will become public.
- The source now rejects tracked credential paths and populated secret entries in `.env.example` during the `secrets` CI job, alongside redacted Gitleaks across fetched branch/tag history and current-tree archives. Additional ignore patterns cover operator secret files and directories. Future production API/provider tokens are to be mounted from protected host files outside the checkout, not committed to GitHub.
- Publication is blocked until the large `v0.1.0` image archive and other release assets pass the read-only private-repository asset audit, a final four-job CI pass is green, and the owner applies GitHub protection/security settings. The old successful Actions log became retrievable on retry and showed zero recognizable token/private-key matches; three cancelled jobs had no recorded steps, and no attached artifacts were found across the initial 142 runs. GitHub branch protection, required `python`/`containers`/`secrets`/`security` checks, security settings, and visibility are owner-controlled UI actions unavailable through the current integration. Do not change visibility until these gates pass. No API host or container service is deployed.
- The 11 open Dependabot pull requests remain unmerged pending individual review; a proposed Python 3.14 update conflicts with the supported `<3.14` range.
- The first publication-preparation [remote quality run](https://github.com/supercodingDen/RepoScope/actions/runs/39899230215) found a newly disclosed fixable [`certifi` advisory](https://github.com/advisories/GHSA-6q48-6c7w-9gw2) in `uv.lock` and two matches during a broad directory scan that also included runner-generated files. `certifi` is now locked at 2026.10.19; the directory scan now stages only tracked source. The next [remote run](https://github.com/supercodingDen/RepoScope/actions/runs/39899736122) passed `python` and `secrets` and cleared the source advisory, but both Docker jobs failed because the exact Debian `libpcre2-8-0` version had been superseded. `Dockerfile.postgres` now pins the current `10.42-1+deb12u2` package from the Debian bookworm-security index. A final four-job CI pass is still required.
- The subsequent [remote run](https://github.com/supercodingDen/RepoScope/actions/runs/39900017691) passed `python`, `secrets`, and `containers`; `security` passed source scanning and image builds but found one fixable high-severity finding in the runtime image. Scanning the pinned Python base image identified `libpcre2-8-0` 10.42-1+deb12u1 with an available 10.42-1+deb12u2 fix; the runtime Dockerfile now installs that version. Independent upstream-image scans also identified patched Perl packages needed in the PostgreSQL image and newer Go standard-library fixes absent from the published NATS image. The PostgreSQL Dockerfile pins Debian's current Perl fixes. The NATS Dockerfile builds v2.15.1 with a pinned Go 1.27.3 builder and copies the binary into a pinned runtime base; remote build, smoke, and final image-scan results remain pending.
- Local publication checks: 379 offline tests passed, 80 optional tests skipped; strict mypy passed 132 source files; Ruff lint and format passed; 48 contract exports, 20 schema/example pairs, two OpenAPI documents, and 58 Markdown local-link targets validated. Redacted Gitleaks scans of 299 allowlisted source/configuration files (1.51 MB), the tracked benchmark archive (20.92 MB expanded), and the remaining tracked PowerShell helper found no leaks. Trivy found zero source secrets or fixable high/critical advisories after the lock update. The local `.env` was not opened or copied. These checks do not cover the private release's binary asset.

## T15/T16 source delivery and open acceptance

- Added a production-only Compose topology, Caddy reverse proxy, protected file-based runtime secrets, separate migration credentials, bounded logs, persistent PostgreSQL/JetStream/source volumes, and private infrastructure networks. The local development Compose file remains separate. The old `v0.1.0` images lack the production launcher and must not be used with this topology; a reviewed post-T15 image set is required.
- Added quiescent PostgreSQL/source backup, fresh isolated-project restore, disk-threshold scripts, [deployment](deployment.md) and [operations](operations.md) runbooks, a complete [owner manual-configuration procedure](manual-configuration.md), [R01-R32 acceptance ledger](acceptance.md), handover notes, and a five-minute interview path with qualified SWE/AI bullets.
- Docker Desktop's Linux engine was unavailable during this work, so production Compose execution, image builds, source-volume backup, PostgreSQL restore, hosted HTTPS, restart persistence, external authenticated demo/SSE, rollback, and live paid-provider evaluation are **not verified**. The owner has not supplied host, domain, off-host storage, or live credentials. They are explicit follow-up gates, not completed T15 deployment.
- Public GitHub visibility and protected-branch/security settings remain T14 owner actions. T12 search/non-search p95, semantic quality, live-provider, and single-job 100K ingestion gates remain open; previous T12 measurements are unchanged. See [acceptance](acceptance.md) before claiming final delivery.
- Local verification after these changes: 376 offline tests passed, 80 opt-in tests skipped; strict mypy passed 130 Python files; Ruff lint/format passed; both production Compose variants parsed without a running daemon; three Bash scripts passed syntax checks; 48 contract exports and 20 schema/example pairs plus two OpenAPI documents validated; 57 Markdown files had no broken local links. A redacted source-only Gitleaks pass scanned 296 allowlisted files and found no leaks. The local `.env` was not read or scanned. The synchronized source commit `4d2559636ff598241b73c50a7e609dd60200b425` passed all four [remote quality jobs](https://github.com/supercodingDen/RepoScope/actions/runs/36476597880). Actual production container/host execution remains open.

## T14 private release and remaining public gate

- Added the [release procedure](t14-release.md), v0.1.0 pre-release notes, changelog, issue/PR templates, weekly Dependabot updates, and a guarded release workflow. The NATS release image carries its Apache-2.0 text and attribution; the release job checks project and NATS notice files before archiving.
- The private [v0.1.0 pre-release](https://github.com/supercodingDen/RepoScope/releases/tag/v0.1.0) was created on 2026-09-24 UTC. Its lightweight tag points to `0f97114e983fda541000c16531b22aeab3113dc2`, the same commit that passed all four [release-branch quality jobs](https://github.com/supercodingDen/RepoScope/actions/runs/36036936721) and the [release job](https://github.com/supercodingDen/RepoScope/actions/runs/36037179304). The release job passed its fresh-checkout, empty-volume mock demo before building and publishing six assets: a 261,646,332-byte image archive, three CycloneDX SBOMs, build metadata, and `SHA256SUMS`. GitHub reports the archive digest as `sha256:dcd0b716bc64083423c6e51e0704963b720215abed4ec36ac81520920b6bc453`. The workflow verified the checksum file before upload. Image IDs are config digests; no registry manifest digest or GHCR image is claimed.
- The connected GitHub integration provides Git data writes and CI/release reads, but no repository visibility, branch-protection administration, or direct release-creation operation. The repository's existing ruleset collection was empty and the branch-protection read returned a permission error. The guarded release job requests `contents: write`, but exposes its token only to ref-validation and publication steps, never to the checked-out demo or image builds. Owner-side visibility and protected-branch settings remain open; private release preparation is not the public T14 gate.
- Local verification: 369 offline tests passed and 80 opt-in tests skipped; strict mypy passed 128 files; Ruff lint and formatting passed; 48 contracts and 20 schema/example pairs plus two OpenAPI documents passed; 56 Markdown files had no broken local links; the release YAML structure parsed; redacted Gitleaks scanned 283 allowlisted source/configuration files (1.44 MB) and found no leaks. The isolated Docker smoke passed after the NATS notice change, including migrations, integration, dependency loss/recovery, and shutdown. The local `.env` was not read or included in the scan.

The first T14 candidate commit on `main` (`48044a7bb5b15a66c1f2d8c11ecfb0aaede8cf25`) had three green remote `quality` jobs; its container job failed during the initial Compose `up` command with only a redacted Docker exit code. The same stack passed an isolated local repetition. The cause was not established.

Commit `b0537655f63c84dcb9d9f0bfe7bd8874275b2581` passed all four `quality` jobs on both `main` and `release/v0.1.0`. Its first release workflow failed during fresh-checkout demo verification with a generic error. Safe stage/error classification was added, and the release workflow later passed on the tagged commit. No failed attempt created a tag or release.

The tagged commit's release-branch CI was green, but a separate `main` run on that same commit had one intermittent failure in `test_connection_count_is_bounded`. The test observed a rejected socket close before the accepting thread stored `SOURCE_CONNECTION_LIMIT`. The proxy now stores the failure before closing the rejected socket; the focused test passed 50 repeated local runs, the full 369-test suite and new empty-volume demo passed, and post-release main commit `96e698b8301d622631e3a5fc163f536305c1f538` passed all four [remote quality jobs](https://github.com/supercodingDen/RepoScope/actions/runs/36038151917). The immutable v0.1.0 tag was not moved.

The release commit, jobs, assets, and `main` default branch were verified through GitHub. The repository is still private, so anonymous source/release access remains unverified. GitHub settings for required checks/review, private vulnerability reporting, and public visibility need owner action where the account plan permits them. T14's public gate remains open until those actions and anonymous access checks are complete. T15 hosting and open T12 performance/quality gates are unaffected.

## T13 delivery and verification

- README now covers the actual Python architecture, job lifecycle, public API, source/schema boundaries, retrieval, backpressure, benchmarks, faults, observability, development, roadmap, security, and license. The [demo](demo.md), [configuration](configuration.md), [failure recovery](failure-modes.md), [deployment prerequisites](deployment.md), and [interview guide](interview-guide.md) distinguish the mock local stack from future public release and hosting.
- Apache-2.0 text is in `LICENSE`; `NOTICE`, [third-party dependency/provenance notes](third-party-notices.md), `CODE_OF_CONDUCT.md`, and `SECURITY.md` are present. The runtime image includes the project's license and notices; an image-file check verified their paths. A release-time audit of complete runtime/image notices is still required. The benchmark source archives and vectors remain outside the repository.
- The CLI now accepts `--ref` and the demo pins the small ItsDangerous repository to the previously recorded commit. Two isolated verifications built mock-only Compose stacks on empty disposable volumes, imported that pinned source, completed agent runs, replayed SSE, and verified citations to the pinned commit. The second ran from a clean reviewed source copy after a frozen dependency install, without the owner's local `.env` or old virtual environment. Both cleaned up their own containers and volumes. First-time downloads/build time is explicitly excluded from a five-minute walkthrough promise.
- That real demo exposed an event replay defect: strict Python-mode validation rejected UUID strings nested in persisted citation JSON. The database adapter now validates that stored JSON in JSON mode. A focused test reproduces the cited-completion case; an integration test also carries citations through terminal event replay.

| T13 local check | Executed result |
| --- | --- |
| Full offline pytest | 369 passed, 80 opt-in skipped |
| Strict mypy and Ruff | Passed; 128 Python files type-checked and 181 formatted |
| Contract exports and validation | 48 exports current; 20 schema/example pairs and 2 OpenAPI documents valid |
| Fresh disposable demo | Passed twice, including from a clean source copy and new frozen environment; temporary volumes removed |
| Isolated Docker/Compose smoke | Passed startup, migration, business API, dependency outages/recovery, isolation, and shutdown; two final passes after the license image change |
| Markdown local links | 51 Markdown files checked, 0 broken local links |
| Source-only Gitleaks | 273 reviewed files, 1.42 MB scanned; no leaks found |

The local `.env` file exists but its contents were not inspected. The owner must confirm local secret values privately. The GitHub repository is still private; T14 public visibility/release and T15 host, HTTPS, domain, and backups are not configured. See [operator configuration](configuration.md). T12's 100-ms search p95, 30-ms non-search p95, semantic-quality, live-provider, and 100K single-job gates remain open.

One intermediate Docker smoke invocation returned a generic Docker command failure while building/starting the disposable stack; its runner intentionally suppresses potentially sensitive command output. A stage-traced repetition and a second unmodified repetition both passed. The transient cause was not established, so these later passes do not prove startup is free of intermittent failures.

## T12 delivery and verification

- A fixed benchmark corpus contains 100,029 real code chunks from 4,782 distinct public source files, with a reproducible fingerprint and 200 fixed code-location queries. Raw per-query and per-request results, three measured trials, exact/HNSW sweeps, filtered recall, 32-client application search, SQL plans, a batch/concurrency experiment, and a non-search HTTP profile are documented in the [T12 performance guide](t12-performance.md). The source is not redistributed and no paid provider call was made.
- Migration `0008_generation_chunk_count` stores the published generation's verified chunk count. This removed per-search `count(*)` work and raised the 32-client median QPS from 367.072 to 439.324 while reducing median p95 from 101.421 to 93.397 ms on the baseline index. Warm-cache progression limits exact attribution; all individual trials are retained.
- Migration `0009_tuned_hnsw` builds a higher-connectivity index. With ef_search=420, unfiltered Recall@10 against exact is 0.9235 and filtered `cpython/` Recall@10 is 0.917. Database vector p95 is below 75 ms in all three trials of both profiles. The new index took 359.223 seconds to build on this machine; migrations have an explicit bounded extended deadline.
- The shipped 10-connection search profile delivered 79.762/80.173/80.046 QPS with zero errors, but its p95 was 444.611/438.126/442.384 ms for 32 continuously active clients. The 100-ms search target therefore remains **open**. A separate development-stack `/healthz` HTTP profile also missed the 30-ms non-search target. Live-provider latency, semantic relevance, full-agent overhead and the 30-minute production ingestion gate were not measured by this mock/composite retrieval benchmark.
- A stored full-text-vector change and an inner-product index were tested and rejected after neither improved the measured trade-off. The raw evidence includes both experiments.

| T12 local check | Executed result |
| --- | --- |
| Full offline pytest | 368 passed, 80 opt-in skipped |
| Strict mypy and Ruff | Passed; 127 Python files type-checked |
| Contracts | 48 exports current; 20 schema/example pairs and 2 OpenAPI documents valid |
| Isolated Docker/Compose smoke | Passed startup, all container integration tests, business API, PostgreSQL/Redis/NATS outage and recovery, and graceful shutdown |
| Source-only Gitleaks | 261 reviewed files, 1.37 MB scanned; no leaks found |

## T11 delivery and verification

- Public business routes remain bearer-protected; health/readiness alone are unauthenticated. Public documentation and metrics routes are disabled. Success, error, and oversized-body responses now carry no-store and browser safety headers. The [T11 security review](t11-security.md) records the verified endpoint and resource boundary.
- The API is the only localhost-published role. API/indexer/agent, PostgreSQL, Redis, and NATS run without root. PostgreSQL and NATS use small derived images from immutable upstream digests; the PostgreSQL image patches `libpcre2-8-0` and removes unused `gosu`.
- A checksum-verified Trivy 0.74.0 source-only scan found zero secrets and zero dependency advisories. Image scans found zero fixable high/critical findings in the runtime, PostgreSQL, Redis, and NATS images. Unfixed high/critical advisory counts remain 95 in runtime and 93 in PostgreSQL; they are recorded as residual review items, not waived as safe. CI now repeats these scans and fails on secrets or fixable high/critical findings.
- The isolated Docker/Compose smoke passed after the image and role changes, including migrations, container integration, business HTTP, dependency outage/recovery, and graceful shutdown. The existing development stack was rebuilt without deleting named volumes and is healthy.

| T11 check | Executed result |
| --- | --- |
| Full offline pytest | 361 passed, 80 opt-in skipped |
| Strict mypy, Ruff lint/format | Passed; 118 Python files type-checked, 162 formatted |
| Contracts | 48 exports current; 20 schema/example pairs and 2 OpenAPI documents validated |
| Docker/Compose smoke | Passed startup, migration, container integration, API, three dependency outages/recoveries, isolation, and graceful shutdown |
| Source-only Trivy and Gitleaks | 248 reviewed files, about 1.28 MB; zero secrets and zero lockfile advisories found |
| Image Trivy gate | Runtime, PostgreSQL, Redis, NATS: zero fixable high/critical; unresolved advisories recorded in the T11 guide |
| Live local boundary | Six services healthy; health/readiness 200, metrics/docs 404, unauthenticated job route 401 |

Remote GitHub CI status and an internet-facing HTTPS endpoint are not claimed by these local checks. Hosting, backups, and rollback remain T15.

## T10 delivery and verification

- Private Prometheus metrics now report canonical-route HTTP counts and header latency, dependency readiness, admission rejections, outbox/worker outcomes, and a 15-second PostgreSQL backlog snapshot. A failed snapshot sets its up gauge to zero and backlog gauges to NaN; public HTTP does not expose `/metrics`.
- Structured logs retain safe request/event identifiers and error codes while rejecting untrusted event text, invalid IDs and connection details. All mapped HTTP failures emit one correlated safe log entry.
- Existing database admission and JetStream/worker limits were verified under saturation and replay. New native fault checks cover a provider failure after a durable reservation, a closed database pool changing readiness to 503, and a persisted NATS message consumed and acknowledged after broker restart. The [T10 operations guide](t10-operations.md) maps every claimed failure boundary to executed tests.

| T10 check | Executed result |
| --- | --- |
| Full offline pytest | 354 passed, 80 opt-in skipped |
| Native PostgreSQL/NATS/public GitHub integration | 83 passed, 1 optional benchmark skipped in 87.49 s |
| Strict mypy, Ruff lint/format | Windows and Linux targets passed; 116 Python files type-checked, 159 formatted |
| Contracts | 48 exports current; 20 schema/example pairs and 2 OpenAPI documents validated |
| Independent review | Four fault-evidence/logging findings fixed and rechecked; no remaining Critical or Important finding |
| Redacted source-only Gitleaks | 242 reviewed files, approximately 1.26 MB scanned; no leaks found |

Docker was unavailable at the T10 verification date; local Docker acceptance was completed on 2026-09-24 as recorded above. No paid provider call was made.

## T09 delivery and verification

- Migration `0007_run_events` records ordered run and tool events, backfills a terminal event for historical runs, and stores expiring SSE connection leases. Terminal event and result/failure commit together; worker redelivery cannot append another terminal event.
- Authenticated `GET /v1/runs/{run_id}/events` replays from `Last-Event-ID`, follows new events with keep-alives, and closes at terminal state. PostgreSQL enforces two connections per principal and twenty globally. Terminal timelines expire after 24 hours; a stale request returns HTTP 410.
- The agent adds at most four chunks from one static Python/TypeScript dependency hop, using only the pinned generation's indexed metadata and manifest. Combined evidence remains limited to twelve chunks and 8,000 tokens.
- The [CLI demo](t09-events-and-demo.md) imports a public GitHub repository through the API, waits for indexing, submits a run, resumes SSE, and prints immutable citations. Tests use a mock HTTP transport and make no paid provider calls.

| T09 check | Executed result |
| --- | --- |
| Full offline pytest | 346 passed, 77 opt-in skipped |
| Native PostgreSQL/NATS/public GitHub integration | 80 passed, 1 optional benchmark skipped in 84.75 s; final SSE integration rerun 2 passed |
| Strict mypy, Ruff lint/format | Windows and Linux targets passed; 110 Python files type-checked, 150 formatted |
| Contracts | 48 exports current; 20 schema/example pairs and 2 OpenAPI documents validated |
| Redacted source-only Gitleaks | 232 reviewed files, approximately 1.23 MB scanned; no leaks found |
| Independent review | CLI replay/failure and relative-import findings fixed; disconnect-path SSE lease cleanup retested |

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

## Local container acceptance

On 2026-09-24, Docker Desktop 29.8.0 with Compose v5.5.1 built and started the Linux images. The isolated `scripts/smoke_test.py` run passed migration, all three roles, 74 container integration tests (with three optional cases skipped), authenticated business API, PostgreSQL/Redis/NATS loss and recovery, network isolation, and graceful shutdown. It used temporary credentials and removed only its own volumes. The development stack remains healthy at `http://127.0.0.1:8000`; its named PostgreSQL and JetStream volumes were preserved during the rebuild. A separate stop/start data-retention check and hosted deployment remain open.

Disk limits are enforced by monitoring and finalization checks, with possible transient physical overshoot. Download accounting bounds application-forwarded TLS transport payload; kernel receive buffers are outside that quota. Local imports require a trusted quiescent operator root. These are bounded source controls, not an absolute hostile-host isolation claim.

## Next milestone

Finish T14 by enabling and verifying public repository/release access plus the available owner-controlled security and branch settings. Then T15 is a separately approved hosted HTTPS deployment with backup/restore and rollback proof. The open T12 search-latency, non-search HTTP, semantic-quality, live-provider and single-job ingestion gates remain tracked; they must not be described as passed at final handover. The original overall job deadline still applies to source acquisition and indexing.

The reviewed source is synchronized to the owner's GitHub repository, `supercodingDen/RepoScope`, after each complete task. The D-drive extraction has no persistent local Git history; synchronization uses the connected GitHub integration. A private pre-release exists, while public visibility, hosted deployment, and system installation have not been performed. Earlier T03 evidence remains in `docs/verification/t03-checks.txt`, `t03-native-checks.txt` and the T03 API guide.
