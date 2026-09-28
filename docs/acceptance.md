# T16 acceptance and handover ledger

This ledger maps all [source requirements](requirements.md) to actual artifacts. **Implemented** means source and prior local/CI evidence exist; it does not mean the current T15/T16 changes have passed remote CI. **Partial** and **open** require the listed operator evidence. The project has no public host or live provider verification as of 2026-09-28. Fill the evidence record below after manual configuration; never silently turn a planned check into a pass.

| ID | State | Evidence or remaining gate |
| --- | --- | --- |
| R01 | Implemented locally | [T03 API](t03-api.md), [demo](demo.md); public submission awaits T14 visibility. |
| R02 | Implemented locally | [T04 delivery](t04-delivery.md), [T10 fault matrix](t10-operations.md). |
| R03 | Implemented locally | [Outbox ADR](adr/003-outbox.md), [T04 delivery](t04-delivery.md). |
| R04 | Implemented locally | [Resource bounds](spec.md), [T10 operations](t10-operations.md); hosted capacity open. |
| R05 | Implemented locally | [Acquisition evidence](t05-acquisition.md), [demo](demo.md). |
| R06 | Implemented locally | [AST/context ADR](adr/005-ast-context-and-routing.md), [indexing](t06-indexing.md). |
| R07 | Implemented locally | [Indexing](t06-indexing.md); live embedding cost/quality open. |
| R08 | Partial | [T12 report](t12-performance.md) has 100,029 real chunks; one-job 100K ingestion is unverified. |
| R09 | Implemented locally | [Retrieval](t07-retrieval.md), [T12 report](t12-performance.md). |
| R10 | Partial | 200 fixed queries and raw measurements exist in [T12 report](t12-performance.md); search p95 target missed. |
| R11 | Implemented locally | [Read-only agent](t08-agent.md), [demo](demo.md). |
| R12 | Implemented locally | [Contracts](contracts.md), [demo](demo.md); hosted citations open. |
| R13 | Implemented locally | [SSE guide](t09-events-and-demo.md), [demo](demo.md); external replay open. |
| R14 | Implemented locally | [T10 operations](t10-operations.md); host alerts open. |
| R15 | Implemented locally | [T10 operations](t10-operations.md), [recovery](failure-modes.md). |
| R16 | Implemented locally | [Local fault matrix](t10-operations.md); hosted replay remains open. |
| R17 | Partial | [T12 raw before/after](t12-performance.md); targets still missed. |
| R18 | Implemented | [README](../README.md), [architecture](architecture.md), [ADRs](adr/), [status](project-status.md). |
| R19 | Implemented locally | [Fresh demo](demo.md), [development](development.md); current Docker engine unavailable. |
| R20 | Implemented previously | [CI](https://github.com/supercodingDen/RepoScope/actions), lockfile, tests; current commit's CI pending. |
| R21 | Implemented | [License](../LICENSE), [contribution](../CONTRIBUTING.md), [security](../SECURITY.md). |
| R22 | Open | Repository and pre-release remain private; owner must enable public access and confirm green CI. |
| R23 | Open | [Production configuration](deployment.md) and scripts exist; host HTTPS, persistence, off-host restore, rollback unexecuted. |
| R24 | Partial | [Local five-minute path](demo.md), [interview guide](interview-guide.md); hosted demonstration and final acceptance pending. |
| R25 | Implemented locally | [Type policy](../AGENTS.md), strict mypy; rerun on final source. |
| R26 | Implemented locally | [T03 API](t03-api.md), [contracts](contracts.md). |
| R27 | Implemented locally | [Architecture](architecture.md) and package boundaries. |
| R28 | Implemented locally | [Source controls](t05-acquisition.md), [indexing](t06-indexing.md). |
| R29 | Implemented | [Dependency policy](dependencies.md), frozen [lockfile](../uv.lock), pinned runtime images. |
| R30 | Partial | [Security review](t11-security.md) and secret-file production design; real host secret protection unverified. |
| R31 | Partial | [Model policy](model-policy.md), [agent](t08-agent.md); live routing/evaluation unverified. |
| R32 | Implemented locally | [Context budget](spec.md), [agent policy](t08-agent.md); live spend monitoring open. |

## Evidence record to fill after owner steps

| Item | Required value and proof | Current value |
| --- | --- | --- |
| GitHub publication | Signed-out source/release URLs, visibility date, ruleset, vulnerability reporting | Private pre-release only; open |
| Source and CI | Exact deployed SHA and successful four-job Actions URL | Post-T15 SHA/CI to record |
| Images | Application/PostgreSQL/NATS IDs, archive SHA-256, Caddy/Redis manifest digests | To record after reviewed build |
| Host | Provider, region, CPU/RAM/SSD/OS/Docker, cost cap, date | Not selected |
| Endpoint and security | DNS, HTTPS certificate/expiry, 80/443-only scan, 401 auth proof | Not configured |
| Workflow demo | Permitted source, pinned commit, job/run IDs, citations, SSE replay, live/mock label | Hosted run not performed |
| Persistence and recovery | Restart proof, backup age/off-host URI, isolated restore, outbox reconciliation, rollback and durations | Not performed |
| Benchmark | Reference hardware, 100K one-job run, 200-query raw trials, p95/QPS/recall, semantic review | See [T12 misses](t12-performance.md); open |
| Limits | Single-host failure domain, paid-call setting, unresolved findings, exact acceptance deviations | Record before final handover |

The [manual configuration procedure](manual-configuration.md) specifies the owner actions. A local script or static Compose parse is not external deployment proof.
