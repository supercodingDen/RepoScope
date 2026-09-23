# T03 persistent work admission

The API accepts durable work and provides status. Indexing and agent execution remain later milestones; newly accepted work stays queued in T03. No repository is cloned and no model is called.

## Configuration

Set `REPOSCOPE_API_TOKEN` yourself to a private random bearer token. Keep it out of source control, URLs and logs. With no token configured, business endpoints fail closed; public health remains available. `REPOSCOPE_PRINCIPAL_ID` identifies the deployment's owner and defaults to `00000000-0000-0000-0000-000000000001`. Keep this identifier stable across restarts. This is a single-owner deployment, not a multi-user identity provider.

Compose passes these values to application roles. Applications read environment variables only. The developer manages the local dotenv file; automated tests generate separate temporary credentials.

## Endpoints

| Method and path | Result |
| --- | --- |
| `POST /v1/repositories` | HTTP 202 with repository and queued job identifiers |
| `GET /v1/jobs/{job_id}` | Persisted ingestion status owned by the configured principal |
| `POST /v1/runs` | HTTP 202 with a run pinned to the active ready generation |
| `GET /v1/runs/{run_id}` | Persisted run status owned by the configured principal |

All four require `Authorization: Bearer <token>`. Both POST endpoints also require an `Idempotency-Key` containing 1–128 visible non-space ASCII characters. Reuse the same key when retrying the same logical request; use a new key for a new submission. The server scopes keys by owner and route, canonicalizes validated request fields including defaults, and replays the original accepted response. Reusing a key with a different body returns HTTP 409. Unknown or differently owned objects return HTTP 404. Request bodies are bounded to 64 KiB, including streamed bodies.

Repository input is `{"url":"https://github.com/owner/repository","requested_ref":"HEAD"}`; the reference defaults to `HEAD`. Run input is `{"repository_id":"<UUID>","question":"Explain the entry point"}`. A run requires an active ready index with a pinned commit SHA. T03 alone cannot create that ready index; it returns `INDEX_NOT_READY` until later indexing work supplies one. Integration tests seed a ready generation through operator SQL only.

## Atomicity and admission

Migration `0002_core` adds repositories, source revisions, index generations, jobs, runs, outbox events, idempotency records, consumer work, reservations and a deployment admission lock. The existing bootstrap migration remains unchanged. Runtime database privileges permit business DML and migration-ledger reads, with DDL reserved to the migrator.

Each submission commits its work, canonical outbox event and replay response in one PostgreSQL transaction. Run reservations commit in that same transaction. A failed event insert rolls everything back. T03 does not publish or consume these events; T04 owns that work.

A database lock serializes admission across API processes. The deployment shares a limit of 100 queued/running ingestion jobs and runs. Existing idempotent responses are replayed before capacity, budget or generation checks. Replay records are retained indefinitely in T03, satisfying the minimum seven-day and until-terminal requirements without premature cleanup.

Budgets use exact decimal arithmetic: USD 0.10 per run, USD 1.00 per UTC day and USD 4.00 for the project. Reserved, settled and uncertain amounts count; released reservations do not. Mock mode reserves zero because it makes no paid calls. Tests inject nonzero estimates to exercise atomic limits; clients cannot choose their own reservation or enable live providers through a request.

## Verification

Run the ordinary tests and quality checks described in [development.md](development.md). Real database tests require an isolated PostgreSQL 17 database with pgvector and these environment variables: `RUN_INTEGRATION_TESTS=1`, `MIGRATION_DATABASE_URL`, `DATABASE_URL`, and `APP_DATABASE_PASSWORD`. They mutate and clear business tables, so use a disposable test database only. Explicitly enabling integration tests without all required connection settings fails.

`python scripts/smoke_test.py` builds an isolated Compose stack, runs the database integration suite, then verifies authenticated admission, replay, conflict and job retrieval through actual HTTP. It also retains dependency recovery and graceful shutdown checks. See [project-status.md](project-status.md) for checks actually executed and remaining container acceptance.
