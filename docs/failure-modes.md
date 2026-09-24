# Failure modes and recovery

RepoScope accepts work only after a database transaction commits the job or run together with its outbox event. JetStream delivery can repeat; consumer completion, fencing, and idempotency prevent duplicate **committed** business output. External provider calls can repeat after a crash, so billing is not exactly once. The [T10 operations guide](t10-operations.md) links each tested boundary to its test.

| Symptom | Expected behavior | Safe operator action |
| --- | --- | --- |
| `/readyz` returns 503 while `/healthz` returns 200 | A dependency is unavailable; liveness does not imply readiness. | Check `docker compose ps` and the private structured logs for PostgreSQL, Redis, or NATS; restore the failed service, then wait for readiness. Avoid resetting volumes. |
| Admission returns 429 | Shared backlog or budget limit is reached. Matching idempotency replay remains available. | Wait for queued work to drain; inspect private backlog metrics. Do not increase concurrency without measuring database and provider limits. |
| Import or run remains queued after NATS loss | The committed outbox row remains pending and can publish after recovery. | Restart the broker, then observe outbox lag and the job/run status. Do not submit duplicate work with new idempotency keys as a recovery shortcut. |
| Worker stops during indexing or a run | A lease expires and a later fenced attempt resumes or reaches a durable failure within its deadline. Partial generations are not searchable. | Restore the worker, check its safe job/run failure code and retry counters, and keep the original identifiers for diagnosis. |
| Redis is unavailable | Cache data is disposable, but paid/work-creating admission fails closed when its required control is unavailable. | Restore Redis and retry after readiness returns; do not bypass admission. |
| Provider timeout or missing live credentials | A safe failure code is persisted; uncertain reserved spend may remain charged conservatively. | Check locally configured provider mode, key presence, price verification, and budget settings without printing credentials. Mock mode needs no paid key. |
| SSE disconnects | Ordered events remain in PostgreSQL during retention. | Reconnect with the last `id` in `Last-Event-ID`. After the 24-hour terminal retention period, a stale cursor returns HTTP 410; read the terminal run resource. |
| Database storage or schema change fails | The migration role owns DDL; runtime roles cannot repair schema. | Preserve data, inspect migration status, take a backup before future production upgrades, and use a reviewed forward migration. Do not hand-edit an applied migration. |

The local isolated smoke test stops and restarts PostgreSQL, Redis, and NATS, verifies readiness transitions, runs integration checks, and checks graceful shutdown. It uses its own disposable Compose project and removes only its own volumes. A stop/start persistence check on the owner's normal volumes and an off-host backup/restore exercise are still T15 work. See [deployment](deployment.md) before exposing anything outside localhost.
