# Operator configuration

The source checkout and default mock stack do not require a model account. `.env.example` lists settings but contains no secret values. `.env` is local-only and must never be read into a report, copied into an archive, or committed. Compose uses it for interpolation; the application itself reads its process environment.

| Setting or decision | When needed | Status and action |
| --- | --- | --- |
| `POSTGRES_PASSWORD`, `APP_DATABASE_PASSWORD`, `REPOSCOPE_API_TOKEN` | Local authenticated Compose demo | Set three distinct random hexadecimal values of at least 32 characters in the local `.env`. The CLI terminal needs the same API token. The actual values are intentionally not inspected by documentation checks. |
| Docker Desktop/Engine and Compose | Local containers | Install/start Docker, verify `docker compose version`, and allow image downloads. The host API is loopback-only. |
| `OPENAI_API_KEY`, `PROVIDER_MODE=openai`, `ALLOW_PAID_API_CALLS=true`, verified current prices and budgets | Optional live embeddings/agent | Leave disabled for the mock demo. The operator must supply a key privately and verify current prices before any paid call; see [provider policy](model-policy.md), [indexing](t06-indexing.md), and [agent](t08-agent.md). |
| Public repository visibility, protected branch/check rules | T14 public release | A private v0.1.0 pre-release exists, but the repository remains private. The owner must enable public visibility and configure available required checks/review rules; then verify signed-out source and release access. See [T14 evidence](t14-release.md). |
| Linux host, budget, domain, DNS, TLS, firewall, protected runtime secrets, off-host backup destination | T15 hosted deployment | No host or public HTTPS endpoint is configured. Select these before deployment; see [deployment](deployment.md). |
| Private security-reporting channel | Before public release | Configure GitHub private vulnerability reporting after the repository becomes public, or publish another private contact method in [SECURITY.md](../SECURITY.md). |
| Exact 8-vCPU/16-GiB reference host and live provider evaluation | Open T12 acceptance | Required for remaining latency, semantic relevance, and 100K single-job claims; see [performance](t12-performance.md). |

The current local stack has previously passed the isolated Docker smoke test, but this table does not infer the contents of anyone's `.env` or confirm that optional live/hosting settings exist. Changing PostgreSQL's bootstrap password in `.env` after its volume was initialized does not rotate the database role; follow a deliberate credential-rotation procedure. Do not delete named volumes to change a password.
