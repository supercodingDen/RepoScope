# RepoScope

Event-driven code intelligence with source-grounded answers and bounded agent costs.

**Current milestone: T02 — application skeleton and quality gates.** FastAPI lifecycle, separate indexer/agent entry points, dependency readiness, one-shot migrations, Docker Compose, and CI are included. Executed evidence and container acceptance status are recorded in [project status](docs/project-status.md). Import, search, and agent business workflows arrive in later tasks.

## Start

Prerequisites: Docker with Compose, Python 3.12.14 and uv 0.12.11. Open the repository directory in VS Code.

```text
uv sync --frozen --all-groups
```

Copy `.env.example` to `.env` locally. Set distinct random hexadecimal `POSTGRES_PASSWORD` and `APP_DATABASE_PASSWORD` values (at least 32 characters). Keep providers mocked.

```text
docker compose up --build --wait --wait-timeout 180
```

Use [health](http://127.0.0.1:8000/healthz) and [readiness](http://127.0.0.1:8000/readyz). Data services and worker management ports are private. The [development guide](docs/development.md) covers Windows setup, shutdown, and dependency-failure tests.

## Verify

```text
uv run --frozen python scripts/export_contracts.py --check
uv run --frozen python scripts/validate_contracts.py
uv run --frozen pytest -q
uv run --frozen mypy
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python scripts/smoke_test.py
```

The last command needs a running Docker daemon and uses an isolated disposable Compose project. It verifies startup, real readiness, migrations, outages/recovery, and graceful shutdown. Offline tests do not substitute for this gate.

## Architecture

Three Python roles share typed contracts and a layered package: FastAPI API/control plane, indexer, and agent. PostgreSQL/pgvector owns state, JetStream delivers durable work, and Redis owns disposable admission/cache state. Read [architecture](docs/architecture.md), [specification](docs/spec.md), and [roadmap](docs/roadmap.md).

Source acquisition, retrieval, and read-only agent tools remain future milestones. Repository code must never execute. T02 runtime paths are mock-only and make no paid calls.

## Configuration and secrets

Secret fields in `.env.example` are blank. Configure them locally; never send secrets through chat or include them in archives. `.gitignore` and `.dockerignore` exclude credential files. Processes read only their environment; Compose supplies it.

## Documents

- [Engineering rules](AGENTS.md) and [contribution guide](CONTRIBUTING.md)
- [Development and tests](docs/development.md)
- [Dependencies](docs/dependencies.md) and [runtime image pins](docs/runtime-images.json)
- [State and error contracts](docs/contracts.md)
- [Threat model](docs/threat-model.md) and [model policy](docs/model-policy.md)
- [Requirements](docs/requirements.md) and [status/evidence](docs/project-status.md)

No GitHub remote or hosted deployment was created in T02. Apache-2.0 remains proposed; formal licensing and notices are part of T13.
