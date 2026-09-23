# RepoScope

Event-driven code intelligence with source-grounded answers and bounded agent costs.

**Current milestone: T05 — durable source acquisition and staging.** T02 delivered the runtime and quality gates; T03 added persistent authenticated work admission; T04 added reliable event delivery and recovery; T05 added bounded public GitHub acquisition and a deterministic source manifest. Acquired source is staged for T06 indexing. Retrieval and agent execution remain later milestones. See [project status](docs/project-status.md) for executed checks and the outstanding Docker/Compose acceptance.

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

Source acquisition is implemented without executing repository code. Indexing, retrieval, and read-only agent tools remain future milestones. Provider calls stay mocked by default; no paid provider call was made in the T05 checks.

## Configuration and secrets

Secret fields in `.env.example` are blank. Configure them locally; never send secrets through chat or include them in archives. `.gitignore` and `.dockerignore` exclude credential files. Processes read only their environment; Compose supplies it.

## Documents

- [Engineering rules](AGENTS.md) and [contribution guide](CONTRIBUTING.md)
- [Development and tests](docs/development.md)
- [Dependencies](docs/dependencies.md) and [runtime image pins](docs/runtime-images.json)
- [State and error contracts](docs/contracts.md)
- [Threat model](docs/threat-model.md) and [model policy](docs/model-policy.md)
- [Requirements](docs/requirements.md) and [status/evidence](docs/project-status.md)

Code through T05 is synchronized to the owner's private [GitHub repository](https://github.com/supercodingDen/RepoScope). Public release is scheduled for T14 and hosted deployment for T15. Apache-2.0 remains proposed; formal licensing and notices are part of T13.
