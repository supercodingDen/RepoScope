# RepoScope

Event-driven code intelligence with source-grounded answers and bounded agent costs.

**Current milestone: T06 — bounded indexing and atomic generation publication.** T02 delivered the runtime, T03 persistent work admission, T04 durable event delivery, and T05 pinned source acquisition. T06 consumes that source, writes fenced per-file chunks and embeddings, then publishes a complete generation in one database transaction. Retrieval and agent execution remain later milestones. See [project status](docs/project-status.md) for executed checks and the outstanding Docker/Compose acceptance.

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

Three Python roles share typed contracts and a layered package: FastAPI API/control plane, indexer, and agent. PostgreSQL/pgvector owns durable state and admission, JetStream delivers durable work, and Redis is a disposable runtime dependency. Read [architecture](docs/architecture.md), [specification](docs/spec.md), and [roadmap](docs/roadmap.md).

Source acquisition and indexing never execute repository code. The default embedding provider is a labeled deterministic mock; real retrieval quality is not inferred from it. Explicit live indexing requires a local key, paid-call opt-in, a recently verified price and a daily budget. See [T06 indexing](docs/t06-indexing.md). Retrieval and read-only agent tools remain future milestones. No paid provider call was made in the T06 checks.

## Configuration and secrets

Secret fields in `.env.example` are blank. Configure them locally; never send secrets through chat or include them in archives. `.gitignore` and `.dockerignore` exclude credential files. Processes read only their environment; Compose supplies it.

## Documents

- [Engineering rules](AGENTS.md) and [contribution guide](CONTRIBUTING.md)
- [Development and tests](docs/development.md)
- [Dependencies](docs/dependencies.md) and [runtime image pins](docs/runtime-images.json)
- [State and error contracts](docs/contracts.md)
- [Threat model](docs/threat-model.md) and [model policy](docs/model-policy.md)
- [Requirements](docs/requirements.md) and [status/evidence](docs/project-status.md)

The owner's private [GitHub repository](https://github.com/supercodingDen/RepoScope) is synchronized after each completed task. Public release is scheduled for T14 and hosted deployment for T15. Apache-2.0 remains proposed; formal licensing and notices are part of T13.
