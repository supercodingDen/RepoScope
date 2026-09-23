# Development and verification

## Prerequisites

Use Python 3.12.14, uv 0.12.11, and Docker Desktop or Docker Engine with a current Compose plugin. The local Windows checkout is `D:\RepoScope_project\reposcope`; open that directory in VS Code.

Windows local checks use an isolated Python 3.12.14 environment without modifying Anaconda. Docker Desktop needs its supported WSL 2 or Hyper-V backend. Follow [Docker installation](https://docs.docker.com/desktop/setup/install/windows-install/) and [WSL guidance](https://docs.docker.com/desktop/features/wsl/). A reboot may be required.

```text
uv sync --frozen --all-groups
uv run --frozen pytest -q
uv run --frozen mypy
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python scripts/export_contracts.py --check
uv run --frozen python scripts/validate_contracts.py
```

If uv is not on PATH but the environment exists, use `.venv\Scripts\python.exe -m pytest -q`, `-m mypy`, and `-m ruff` in PowerShell. Select `.venv\Scripts\python.exe` in VS Code. No provider account or API key is needed.

## Start the development stack

1. Copy `.env.example` to `.env` yourself. Set `POSTGRES_PASSWORD` and `APP_DATABASE_PASSWORD` to distinct random values of at least 32 hexadecimal characters. Hex values avoid URL-escaping ambiguity. Set `REPOSCOPE_API_TOKEN` to a separate random token to enable business access. Keep these private.
2. Keep providers mocked. Compose fixes `PROVIDER_MODE=mock` and `ALLOW_PAID_API_CALLS=false`. T03 accepts persistent work; no provider calls or business consumers run yet.
3. Run:

```text
docker compose up --build --wait --wait-timeout 180
```

The one-shot `migrate` service must succeed before application roles start. Check [liveness](http://127.0.0.1:8000/healthz) and [readiness](http://127.0.0.1:8000/readyz); both return HTTP 200 with `{"status":"ok"}` when ready.

`API_PORT` changes the localhost port. PostgreSQL, Redis, NATS, worker health, and metrics have no published ports. Management port 9000 is private to the Compose network. Memory/CPU limits are defaults, not capacity claims. PostgreSQL and JetStream use persistent named volumes; Redis is disposable.

Stop without deleting data:

```text
docker compose down
```

Do not remove persistent volumes unless intentionally resetting the database. Changing bootstrap passwords after initialization does not automatically rotate the PostgreSQL superuser password.

## Process boundaries

- `python -m reposcope api`: public T03 API and health/readiness on 8000 and management on 9000.
- `python -m reposcope indexer`: idle worker lifecycle and management on 9000.
- `python -m reposcope agent`: idle worker lifecycle and management on 9000.
- `python -m reposcope.infrastructure.db.migrate`: one-shot DDL owner.

For local processes, set `PYTHONPATH` to `src;.` on Windows (`src:.` on Linux), and supply environment variables explicitly. Application code never loads dotenv files. Compose supplies container connection settings; container dependency addresses are not exposed as localhost services.

Readiness checks PostgreSQL and the required `0002_core` migration, Redis PING, and JetStream account information with deadlines. It never calls a model. Liveness indicates a responsive process. Dependency failure returns HTTP 503 using the canonical Problem shape and a safe request ID. Workers have no acknowledgment path until T04.

The migration runner owns `src/reposcope/infrastructure/db/migrations`. It creates the vector extension and application schema, records checksums, and grants runtime DML without schema creation. T03 adds the business tables in `0002_core`; see [T03 API](t03-api.md). Runtime roles can read the ledger but cannot modify it. Never edit a migration already applied to a retained database.

## Automated container acceptance

```text
uv run --frozen python scripts/smoke_test.py
```

Wrappers: `bash scripts/smoke_test.sh` or `.\scripts\smoke_test.ps1`. Use `--port 18001` if port 18000 is occupied.

The script ignores local dotenv files, generates temporary credentials in memory, and uses a unique Compose project. It builds images, checks all roles, runs migration and business-transaction integration tests, checks actual HTTP admission/replay/conflict, repeats migration, checks each dependency outage/recovery and public metrics isolation, and requires graceful exit. It deletes only its own containers and volumes in a finally block. It does not operate on your normal development project.

A missing Docker daemon fails this prerequisite. Integration tests skip in ordinary offline pytest and run explicitly inside the Compose test service. Read `docs/project-status.md` for checks actually executed.

## Quality gates

CI checks schema drift, semantic fixtures, Ruff formatting/lint, strict mypy (src/scripts/tests), pytest, compilation, container build/smoke, and Gitleaks. Actions use verified commit pins. Gitleaks 8.30.1 is checksum-verified and redacts findings. Python dependencies retain the frozen uv.lock; T02 and T03 add no third-party Python dependencies.

T03 provides persistent admission and status endpoints. Worker execution, GitHub CI execution and external hosting are separate milestones; local checks do not imply deployment.

### Optional native broker recovery check

A trusted operator-supplied NATS server binary can exercise the production JetStream client without Docker. Set `NATS_SERVER_BINARY` to its absolute executable path, then run `uv run --frozen pytest tests/integration/test_nats_recovery.py -q`. The test starts a localhost-only server with temporary storage, checks the actual client's account probe, stops/restarts the broker, and removes its owned process afterward. It does not test PostgreSQL, Redis, or Linux container compatibility. On Windows, the server subprocess is hidden.

The reconnect loop has one bounded connection attempt at a time, a fixed delay, and lasts until process shutdown so long broker outages remain recoverable. It is independent of the finite business-job retry policy implemented in T04.
