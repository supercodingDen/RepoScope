# Third-party dependencies and provenance

RepoScope's Apache-2.0 license covers its original source and documentation, not upstream packages or container images. The runtime image includes the project's `LICENSE`, `NOTICE`, and this file. The application uses the pinned versions in [`uv.lock`](../uv.lock) and immutable container references in the Dockerfiles and [`docs/runtime-images.json`](runtime-images.json). Installed Python distributions retain their `.dist-info` license files and metadata in the runtime image. The table below records direct runtime distributions observed in the local Python 3.12.14 environment on 2026-09-24; transitive distributions and operating-system packages must also be reviewed when assembling a public release or redistributing images.

| Distribution | Installed version | License identified from installed metadata or included license file |
| --- | ---: | --- |
| fastapi | 0.141.1 | MIT |
| uvicorn | 0.53.0 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| psycopg | 3.3.5 | LGPL-3.0-only |
| psycopg-binary | 3.3.5 | LGPL-3.0-only |
| psycopg-pool | 3.3.1 | LGPL-3.0-only |
| pgvector | 0.5.0 | MIT |
| nats-py | 2.16.0 | Apache-2.0 |
| redis (Python client) | 7.4.1 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| openai (Python client) | 3.14.1 | Apache-2.0 |
| tiktoken | 0.14.0 | MIT, per included license text |
| tree-sitter | 0.26.0 | MIT, per included license file |
| tree-sitter-python | 0.25.0 | MIT |
| tree-sitter-typescript | 0.23.2 | MIT |
| prometheus-client | 0.26.0 | Apache-2.0 AND BSD-2-Clause; its included NOTICE is retained in the installed distribution |

The PostgreSQL/pgvector, NATS, and Redis server images have separate upstream terms; their pinned image references and build stages are in `Dockerfile.postgres`, `Dockerfile.nats`, and `compose.yaml`. The Debian/Python base image also carries operating-system package licenses. Do not infer that this short direct-dependency table replaces their complete notices. The T14 release review must inspect the actual image contents and distribute required license/notice material with the release artifacts. In particular, the installed Psycopg LGPL license texts and Prometheus client NOTICE must remain available.

The small demo downloads a pinned public ItsDangerous revision at runtime. T12's corpus uses an official CPython source release and packages from `uv.lock`; [the benchmark report](t12-performance.md) records the source archive hash and corpus fingerprint. Neither source archive, copied project source, nor derived source vectors are redistributed by this repository. Source license identification is not automatically assumed from a filename; respect each upstream project's license before creating a redistributed corpus.
