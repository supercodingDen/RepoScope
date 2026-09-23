# Dependencies and environment

## Verified T01 environment

Python 3.12.14 on Linux x86_64; uv 0.12.11. The supported Python range is >=3.12,<3.14. The exact local interpreter is recorded in .python-version. Python 3.13 compatibility is resolver-declared, not claimed as executed. T02 must use a matching tested container interpreter before declaring container parity.

The resolver successfully produced uv.lock, and `uv sync --frozen --all-groups` installed the locked environment. Direct dependencies are exact-pinned in pyproject.toml; uv.lock records transitive versions, distributions, and hashes. This establishes dependency resolution/installability, not a completed vulnerability review or database/broker integration.

| Dependency | Pin | Purpose |
| --- | --- | --- |
| FastAPI | 0.141.1 | Typed HTTP transport |
| Uvicorn | 0.53.0 | ASGI runtime |
| Pydantic / settings | 2.13.5 / 2.15.0 | Contracts and validated configuration |
| Psycopg / pool | 3.3.5 / 3.3.1 | Async PostgreSQL and bounded pools |
| pgvector Python | 0.5.0 | Vector adapter |
| nats-py | 2.16.0 | JetStream client |
| redis Python | 7.4.1 | Async cache/admission adapter; this is not the Redis server version |
| HTTPX | 0.28.1 | Async external HTTP |
| OpenAI SDK | 3.14.1 | Async Responses and embedding adapter |
| tiktoken | 0.14.0 | Embedding chunk token counts |
| Tree-sitter | 0.26.0 | Parsing runtime |
| Python grammar | 0.25.0 | Python source parser |
| TypeScript grammar | 0.23.2 | TypeScript and TSX source parsers |
| prometheus-client | 0.26.0 | Metrics |
| Ruff / mypy | 0.16.8 / 1.20.2 | Lint, formatting, strict type checks |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | Offline and future async tests |
| jsonschema | 4.26.0 | Draft 2020-12 validation |
| openapi-spec-validator | 0.9.0 | OpenAPI 3.1 validation |

No sentence-transformers, PyTorch, GPU runtime, LangChain, LangGraph, or additional agent framework is required. The SDK may use its own locked transport dependencies; do not manually downgrade transitive packages without re-resolving and validating compatibility.

## Installation before implementation

```bash
uv sync --frozen --all-groups
uv run python scripts/export_contracts.py --check
uv run python scripts/validate_contracts.py
uv run pytest -q
uv run mypy
uv run ruff check .
```

Use an isolated virtual environment. The commands do not need an API key. Never source or print .env as part of diagnostics. T01 tests import runtime adapters and parse tiny Python/TypeScript/TSX examples to verify grammar ABI compatibility; they make no provider calls.

## Infrastructure contract for T02

PostgreSQL 17 plus pgvector with HNSW/FTS and compatible extension support; NATS 2.x with JetStream durable streams; Redis with the required asyncio client protocol; Docker Compose v2. T02 must select supported patched server images, resolve immutable image digests, check startup/readiness, and record them in compose.yaml and a runtime manifest. No Docker executable is available in this T01 environment, so no image pull, server boot, or container digest verification is claimed here. This readiness gate stays explicit for T02.

The core installation has no Node/React/Next.js dependency. If a frontend is later authorized, add its own package manifest, lockfile, strict tsconfig, generated API client, and lint gates in that task.

Official reference points: [FastAPI async guidance](https://fastapi.tiangolo.com/async/), [OpenAI models](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Tree-sitter parsers](https://tree-sitter.github.io/tree-sitter/using-parsers/), [PostgreSQL support policy](https://www.postgresql.org/support/versioning/). Exact installed versions and hashes are authoritative in the lockfile, rather than prose claims about being the latest.

## T02 local verification update

The frozen Python dependencies also installed successfully on Windows with isolated Python 3.12.14. T02 retains the Python dependency lock unchanged. Dockerfile uses Python 3.12.14 and uv 0.12.11. Registry-verified server image references and digests are recorded in docs/runtime-images.json. Actual image build/boot evidence is tracked separately in docs/project-status.md; registry metadata is not a container compatibility test.



## T05 source transport dependency

Git is an explicit system dependency for isolated source acquisition; no new Python dependency is needed. Dockerfile declares Debian bookworm `git=1:2.39.5-0+deb12u3` and `ca-certificates=20250419~deb12u1`, verified against the official [Git package](https://packages.debian.org/bookworm/git) and [CA package](https://packages.debian.org/bookworm/ca-certificates) metadata on 2026-09-22. The security-patched Debian package version differs from the upstream Windows version. Container installation/build still requires actual Docker acceptance; package metadata is not a successful build claim.

Native Windows source tests use isolated official [MinGit 2.55.0.windows.5](https://github.com/git-for-windows/git/releases/tag/v2.55.0.windows.5), SHA-256 `56d7b226b7693196cfc71fef26568f536c4a021ab6c37ff2db4287bed908e96e`. The installed host Git is not replaced. Configure a trusted binary explicitly; imported repository code/configuration must never choose the executable.

The indexer alone joins the source egress network and stores acquisition artifacts on its own persistent volume. Database, broker and cache remain on the internal backend network with no published ports. Application source policy still validates public GitHub DNS, pins transport destinations, and disables redirects; the network declaration alone is not an SSRF control.
