# T04/T05 final whole-change review

Review date: 2026-09-23 UTC. Authoritative checkout: `D:/RepoScope_project/reposcope`. This review changed no production code, tests, migrations, Git state, or external resources. The only persisted reviewer output is this report. No secret-bearing file was read and no imported code was executed.

Final review status: **approved within T04/T05 scope; all three findings below are closed** after the scoped fix re-review recorded at the end. The historical findings and original reproductions are retained for evidence. Final broad verification remains parent-owned, and the Linux container gate remains open.

## Findings

### P2 — Dependency errors in the new janitor terminate the entire indexer role

Locations: `src/reposcope/application/source.py:104` (`run_cleanup`), `:95` (`cleanup`); composition at `src/reposcope/roles.py:61`.

`run_cleanup` catches only `OSError` and `SourceRejected`. The calls to `repository.cleanup_candidates()` and `repository.cleaned()` can raise psycopg `OperationalError`, pool acquisition errors, or a transaction `TimeoutError`. Those errors escape the janitor task. Because it belongs to the role's `TaskGroup`, the failure cancels the worker and management server and exits the process. A routine PostgreSQL outage therefore changes the established dependency-loss behavior from a live process reporting degraded readiness into indexer termination. Container restart may recover later, but it does not satisfy the existing readiness/recovery contract and does not protect the native process.

Evidence: a read-only in-memory invocation of the actual `SourceAcquisitionHandler.run_cleanup` with a source-repository fixture raising a synthetic psycopg `OperationalError` immediately leaked `OperationalError`. The `TaskGroup` consequence follows directly from the inspected role composition. No real dependency disruption was performed by this reviewer.

Fix: keep cancellation propagating, but handle dependency failures at the janitor loop boundary with a safe fixed log code and bounded retry/wait. Add a regression that fails the repository once, verifies the cleanup loop remains alive, then demonstrates subsequent cleanup and orderly cancellation/recovery.

### P2 — Finalization bypasses the last disk/deadline/cancellation check

Locations: `src/reposcope/adapters/source_storage.py:333-334`, `:112-130`; remote call at `src/reposcope/adapters/source_git.py:364-367`.

The local importer checks resource limits before reading/writing each entry, but never checks after the last blob is written. `finalize()` adds the manifest and renames the snapshot out of the monitored attempt before validating its contents. It does not consult the acquisition deadline or cancellation token. Remote acquisition checks immediately before finalization, but still omits the manifest growth and time spent in final hashing/validation. Successful import can therefore retain data beyond the configured disk limit, and finalization can return success after the acquisition deadline. This is persistent accepted overrun, not the documented transient polling overshoot.

Evidence: executed actual `LocalSourceImporter.acquire` in a private temporary fixture with a single `a.txt` containing 100 bytes and `SourceLimits(disk_bytes=1)`. It returned success with `eligible_bytes=100`; the resulting snapshot contained 354 physical file bytes. No mocks were used for this reproduction.

Fix: account for the final blob and written manifest before rename, preserve deadline/cancel checks through final validation, and refuse staging after the acquisition budget expires. If failure occurs after a new destination was created, remove only that newly created, unreferenced destination; local imports have no database janitor. Do not remove an already existing validated snapshot. Add one-file low-disk-limit, manifest growth, finalization-deadline, cancellation, and cleanup regressions.

### P2 — Concurrent obsolete cleanup can permanently fail an otherwise recoverable job

Locations: `src/reposcope/adapters/source_storage.py:92-110`, `:180-187`; foreground call and mapping at `src/reposcope/application/source.py:39`, `:66-67`; periodic cleanup at `:95-102`.

Both foreground retry acquisition and the periodic janitor can select and remove the same obsolete namespace. The store uses existence checks followed by ordinary `rmtree`; it is not idempotent under concurrent removal. A sharing violation from a still-running stale Windows process is another possible temporary deletion failure. When foreground cleanup raises `OSError`, `handle()` converts it into `PermanentFailure("SOURCE_IO_FAILED")`, causing durable job failure even though the current token could retry safely. The janitor's own OSError catch does not protect the foreground path.

Evidence: executed two real concurrent `SourceStore.cleanup` calls against the same private owned attempt, synchronizing only immediately before the actual `shutil.rmtree` calls so both pass the initial existence checks. Native Windows results were `success` and `PermissionError`. No source-store code was changed. The terminal classification is directly visible in the handler.

Fix: make missing/concurrent removal idempotent, avoid treating ordinary sharing/transient cleanup failures as permanent source corruption, and retry/defer safely while preserving fencing and authoritative manifest-reference checks. Add an actual concurrent cleanup regression plus a handler regression proving temporary cleanup failure does not terminalize the job. Do not weaken containment or erase another attempt's referenced snapshot.

## Broad review evidence and accepted behavior

Read the engineering contract, specification, architecture, threat model, ADR-003, current execution plan, scratch T05 brief, T04/T05 reports, acceptance ledger, and prior focused routing/transport reports. Inspected delivery/source domain types, ports, application services, PostgreSQL/NATS/Git/process/transport/storage adapters, additive migrations 0003/0004, runtime role/settings changes, source wire contracts and admission validators, local CLI, Dockerfile/Compose/smoke changes, provenance metadata, and related tests.

- T04 publication claims, stable event identity, publisher confirmation, durable counters/backoff, consumer authorization against authoritative outbox JSON/scope, completion-before-ACK, and fresh locked lease checks remain intact. Database SDKs stay in adapters; domain/ports do not import network/database SDKs.
- Reconciliation separates original requests from source continuations. The previously identified fifth-attempt staged-success failure is fixed in both candidate selection and the locked terminal update. Overall job deadline handling still applies, preserves the source manifest, and promotes staged completion to a terminal failure when appropriate.
- Source commit pinning occurs before body acquisition, under the fenced consumer/business locks. Job, generation, revision and manifest database constraints preserve repository/principal/commit identity. Stage completion, manifest metadata and source continuation are one transaction; ready-index/succeeded-job behavior is not fabricated.
- Git operates on fresh owned bare object storage with an isolated environment and argument arrays. Each network command resolves/validates public numeric destinations, uses the bounded GitHub-only CONNECT transport, and retains TLS hostname verification. Blobless object inventories reject unrequested blob objects; secret-path filtering precedes approved blob content reads. There is no checkout, repository build/install, recursive submodule execution, or provider invocation.
- Source path rules reject traversal, special Windows names, ADS, controls, links/reparse points, and case-folded directory spelling collisions. Local imports remain an explicit operator CLI/service under a trusted quiescent root; no public local-path route was added.
- Windows owned subprocess behavior uses suspended creation and JobObject assignment before resume. Existing tests exercise actual child processes, timeout/output/disk bounds and descendants that outlive the parent. POSIX code uses process groups; its runtime execution was not independently established here.
- Transport budget accounting is shared across tunnels and debited across commands. Both half-close directions have real socket regressions; prior focused reviewer independently reran 11 cases after the fix. No further transport destination/forwarding bypass was identified in the broad scan.
- Manifest storage is content-addressed, sorted, revalidated, and stored under job/token namespaces. Obsolete/terminal cleanup selection is authoritative and excludes manifest references. Crash-after-files-before-database and pinned retry tests are present. The three findings above concern remaining resource/recovery gaps, not an observed stale-writer publication bypass.
- Canonical source continuation contains IDs, policy revision and manifest digest only. Admission changes preserve public GitHub restrictions and reject unsafe references before repository work. Existing T03 service/HTTP persistence controls were not found weakened by these additions.
- Benchmark metadata records the actual supplied public-source result: commit `672971d66a2ef9f85151e53283113f33d642dabd`, manifest `7fb39a96d85f32060b90849bc4da4dca84e109bdc5e9f6d9d06a4a4521257ebb`, 49 eligible files. Automatic license classification remains `unknown`; separately supplied upstream BSD metadata is labeled as such. No repository source is redistributed there.

## Verification limits and honest claims

The reviewer executed only the three targeted reproductions described above; costly full suites were intentionally left to the parent's concurrent verification. Reported parent evidence includes an earlier 57 real PostgreSQL/NATS/public-Git tests passing and a current offline 299 passed / 55 skipped checkpoint. Those are parent evidence, not independently rerun results, and later fixes require fresh affected checks.

The test suite's moving-ref/crash-gap source adapter is a port fixture over real PostgreSQL, while the API/broker/public-source handoff uses the real Git adapter and real public network. The hostile object test uses actual Git object plumbing but stubs remote fetch; the separate opt-in public and tiny-download-limit tests exercise production networking. These distinctions should be preserved when describing coverage.

No Docker/Compose/Linux-container execution occurred. Container Git differs from the tested Windows MinGit; its execution remains part of the explicitly open container gate. Do not infer that gate from native successes. No T06 indexing, T08 agent execution, hosted deployment, commit, or publication acceptance is asserted.

## Follow-up

Re-review the three fixes and their targeted regression evidence, then update this report's status. Final project status and acceptance ledger should reflect the parent's completed checks and preserve the open container gate.

## Scoped fix re-review — final verdict

Inspected the final changes in `source_storage.py`, `source_process.py`, `source_git.py`, `application/source.py`, their storage/lifecycle regressions, and the small Dockerfile runtime CLI copy. **All three findings are closed; no new blocking defect was identified in this fix wave.** No production or test files were modified by this reviewer.

1. **Janitor dependency recovery: closed.** The periodic boundary now catches ordinary exceptions, emits only a fixed safe warning/code, and retries after a bounded interval. `CancelledError` remains outside that catch. Independently repeated the original synthetic psycopg outage probe with a repository that fails once and then recovers: the actual loop remained alive, made three calls, and propagated cancellation. Inspected the new real-PostgreSQL lifecycle regression, which also checks that the synthetic sensitive diagnostic is absent from logs. Implementer evidence for the two added real-PostgreSQL lifecycle cases is 2 passed; the parent's final real-service rerun remains separate.

2. **Finalization resource checks: closed.** Both local and Git production callers pass their active monitor into finalization. Local acquisition checks after the last blob; finalization checks after manifest write and before rename, validates time/cancellation between metadata/blob checks, and checks again after validation. A failure removes only a newly created destination; an existing destination is retained. `ProcessRunner.check()` now checks time both before and after its disk scan. Independently ran regressions for one-byte/manifest-only disk overflow, deadline expiry during final validation for new and existing destinations, and cancellation between blob reads. The tests assert cleanup and preservation behavior as appropriate.

3. **Concurrent cleanup/retry classification: closed.** Owned deletion now tolerates missing/concurrently removed paths and retries transient sharing races with a finite bounded delay. Foreground `OSError` becomes `TransientFailure("SOURCE_IO_FAILED")`, preserving the existing bounded delivery retry policy. Independently repeated the original stricter concurrency reproduction, synchronizing both callers immediately before actual removal: results were `success`, `success`. The suite also passes its real concurrent removal test, and the added real-PostgreSQL handler regression checks sharing failure remains transient.

Independent focused command from the project, using a fresh dedicated scratch `--basetemp`: `python -m pytest tests/test_source_storage.py tests/test_source_process.py tests/test_source_transport.py -q -p no:cacheprovider`: **37 passed in 3.32 seconds**. The first invocation used pytest's default shared Windows temp directory and hit fixture-setup permission errors (11 socket-only tests passed, 26 fixtures could not initialize); rerunning with the isolated writable scratch directory resolved that environment issue. No product failure was observed in the corrected run.

The Dockerfile now copies the single operator CLI into the runtime image alongside its existing source/contracts dependencies. This fixes the packaging omission without mounting a local import tree by default. Container build/execution and actual Linux Git remain unexecuted here and are still explicitly open acceptance evidence, not inferred from this approval.
