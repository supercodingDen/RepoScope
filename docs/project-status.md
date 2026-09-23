# Project status

Milestone: **T04 and T05 implemented and verified in the native Windows environment**.
Verification date: 2026-09-23 UTC. Working project: `D:\RepoScope_project\reposcope`.

## Delivered

- T04: transactional outbox publication, bounded durable JetStream consumers, renewable fenced leases, durable retries, completion-before-ACK, safe quarantine and stalled-work reconciliation.
- T05: canonical public GitHub admission, immutable commit pinning, isolated blobless Git acquisition, controlled public-IP transport and download accounting, file/path/secret exclusions, process-tree termination and bounded storage.
- Deterministic source manifests and scoped durable `repo.source.acquired` continuations committed atomically with source-stage completion. Public sources are staged for T06; no index-ready or completed-agent result is fabricated.
- Operator-only local snapshot CLI, authoritative obsolete/terminal cleanup, transient cleanup recovery and safe finalization rollback.
- Additive migrations0003/0004, exported contracts, runtime configuration, source volume/indexer egress, pinned Git/CA dependencies and smoke-test updates.

Usage: [durable delivery](t04-delivery.md), [source acquisition and local import](t05-acquisition.md), [existing HTTP API](t03-api.md). Scope proof: [acceptance ledger](plans/2026-09-22-t04-t05-acceptance.md).

## Executed verification

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

T06: bounded indexing/chunking, reproducible embeddings and atomic ready-generation publication. Until T06 is implemented, source acquisition stops at the durable staged handoff; the original overall job deadline still applies. T08 agent execution is also not implemented by this delivery.

The reviewed source was synchronized to the owner's private GitHub repository, `supercodingDen/RepoScope`, on 2026-09-23 UTC (initial import commit `2c0e6f015588db0906c8ba50cb0448e5a505acfe`). The D-drive extraction has no persistent local Git history; synchronization used the connected GitHub integration. Public release, PR, hosted deployment and system installation were not performed. Remote CI results have not been verified. Earlier T03 evidence remains in `docs/verification/t03-checks.txt`, `t03-native-checks.txt` and the T03 API guide.
