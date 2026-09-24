# Five-minute local demo

This path demonstrates durable import, a read-only agent run, SSE replay, and immutable citations with **mock** embeddings and a mock agent. It is not a semantic-quality evaluation. The small public [ItsDangerous repository](https://github.com/pallets/itsdangerous) is pinned to commit `672971d66a2ef9f85151e53283113f33d642dabd`, the same revision recorded in [the source manifest](../bench/data/repositories.json). Its source is downloaded during the demo; no imported code is executed or redistributed here.

## Prepare once

From a fresh source checkout, install Python 3.12.14, uv 0.12.11, and Docker with Compose. Run `uv sync --frozen --all-groups`. Copy `.env.example` to a local `.env` and set three **distinct** random hexadecimal values of at least 32 characters: `POSTGRES_PASSWORD`, `APP_DATABASE_PASSWORD`, and `REPOSCOPE_API_TOKEN`. Leave `PROVIDER_MODE=mock` and `ALLOW_PAID_API_CALLS=false`. The token must also be set in the terminal that runs the CLI. Never paste a real token into source, documentation, chat, or screenshots.

Start the stack with `docker compose up --build --wait --wait-timeout 180`. Both `http://127.0.0.1:8000/healthz` and `http://127.0.0.1:8000/readyz` should return HTTP 200. On Windows PowerShell, set the CLI environment variable with `$env:REPOSCOPE_API_TOKEN = '<the same locally configured token>'`; on bash, use `export REPOSCOPE_API_TOKEN='<the same locally configured token>'`. These examples are placeholders, not usable credentials.

The first image build and Python/tokenizer downloads can exceed five minutes. The timed walkthrough starts after the images are built and the stack is ready; public GitHub download and indexing time depend on the network and host. If port 8000 is occupied, set `API_PORT` locally and pass the matching `--api-url` below.

## Walkthrough

```text
uv run --frozen python scripts/demo.py https://github.com/pallets/itsdangerous "Where is URL-safe signing implemented?" --ref 672971d66a2ef9f85151e53283113f33d642dabd --api-url http://127.0.0.1:8000
```

The CLI submits an idempotent import, polls the visible job, submits a run, follows the authenticated event stream, reconnects with `Last-Event-ID` if interrupted, and prints the final answer plus `path:start-end`, commit SHA, and chunk identifier for each citation. A mock answer may be an excerpt or may report insufficient evidence; check the printed locations instead of assuming it has understood the question. The CLI has a 30-minute overall deadline.

Try a scoped search separately using the [public API contract](../packages/contracts/openapi/public.yaml). Every business request needs `Authorization: Bearer <your local token>`; creation requests also need a unique `Idempotency-Key`. A missing token returns HTTP 401. The API's `/metrics` and interactive docs are intentionally unavailable on the host.

Run `docker compose down` to stop the demonstration without deleting PostgreSQL and JetStream data. Repeating the walkthrough against the same volumes may reuse an existing completed generation; use an isolated test project if a fresh-ingestion measurement is required. The [development guide](development.md) describes an isolated disposable Compose smoke test. The full [T12 benchmark](t12-performance.md) has its own corpus and database and is not part of this quick demo.

If the CLI reports a failed import, inspect the job's safe failure code and check the [recovery guide](failure-modes.md). If readiness is 503, check PostgreSQL, Redis, and NATS health with `docker compose ps` before retrying. Never reset volumes to solve a routine connectivity error.

Maintainers can repeat the full flow on independent empty volumes with `uv run --frozen python -m scripts.verify_demo`. It generates temporary credentials in memory, disables local dotenv loading, forces mock mode, verifies a citation to the pinned commit, and removes only its own Compose project. It needs public GitHub network access and may take longer than the small interactive walkthrough because it builds images first.
