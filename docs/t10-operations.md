# T10 operations and fault matrix

## Private metrics and logs

Each role serves Prometheus metrics only on its private management endpoint, `/metrics`. The public API does not expose that route. Metrics have fixed labels: canonical API route, method and HTTP status; dependency name; work kind; worker consumer and outcome. Request IDs, repository paths, URLs, prompts, credentials and exception text are never metric labels. The HTTP latency histogram measures time to response headers, so streaming duration is excluded.

`reposcope_dependency_ready` records the last bounded readiness probe for PostgreSQL, Redis and JetStream. `reposcope_work_backlog` records queued/running jobs, queued/running agent runs and unpublished outbox rows whose work is still active and before its deadline. `reposcope_work_snapshot_up=0` means the latest PostgreSQL sample failed; backlog values become NaN rather than showing stale counts as current. The API role samples every 15 seconds. Counter families cover public HTTP responses, work admission rejections, outbox publication and worker delivery outcomes.

JSON logs emit a symbolic event and a small validated context set: UUID request/job/run/event identifiers, fixed role/resource names, and uppercase safe error codes. They do not format exception messages. Correlate an HTTP rejection with its `X-Request-ID`, then use an outbox event ID to trace worker retries. Do not use logs as a source for prompts or source content.

## Backpressure

The PostgreSQL admission lock enforces a deployment-wide ceiling of 100 queued/running jobs and agent runs. A new request above the ceiling receives HTTP 429; a matching idempotency-key replay still returns its original acceptance. Per-process worker concurrency remains two, JetStream pull consumers limit ACK-pending messages, and the broker stream has finite message and byte caps. These are conservative controls for a single-host demonstration, not a measured throughput claim. The private backlog gauges make saturation visible.

## Fault matrix

| Boundary | Expected safe behavior | Executed evidence |
| --- | --- | --- |
| PostgreSQL read/admission outage | HTTP 503, no credentials in body; failed backlog sample marked down | `test_closed_database_pool_is_safe_unavailable`; `test_sampler_marks_failure_without_exposing_connection_text` |
| Admission lock and capacity | One committed request per idempotency key; 429 at capacity; replay preserved | `test_shared_capacity_and_budget_races`; `test_capacity_rejects_new_work_but_preserves_idempotent_replay` |
| Database wait cancellation | No partial run, reservation or outbox record | `test_cancelled_database_wait_does_not_leave_work` |
| JetStream restart | Existing client reconnects and resumes durable delivery | `test_real_jetstream_client_recovers_after_broker_restart` |
| Publish-before-mark and complete-before-ACK crash gaps | Duplicate publication/consumption commits only one business outcome | `test_publish_ack_gap_and_completion_ack_gap_are_idempotent` |
| Worker cancellation and expired lease | External work cancelled; old fence cannot checkpoint or finalize | `test_shutdown_cancels_work_without_terminal_failure`; `test_expired_worker_cannot_heartbeat_checkpoint_or_finalize` |
| Missed broker delivery or exhausted attempts | Deadline reconciler commits a finite terminal failure | `test_deadline_reconciles_never_delivered_and_exhausted_work`; `test_transient_retry_is_durable_and_does_not_reset_attempts` |
| Model provider outage after reservation | Safe terminal failure; uncertain reservation retained; no provider detail returned | `test_provider_outage_keeps_reserved_cost_and_commits_safe_failure` |
| Redis/readiness outage | Health stays live; readiness returns 503 and component gauge reports down | `test_readiness_exposes_bounded_component_gauges_privately` |

The native Windows integration suite runs against isolated PostgreSQL and NATS processes. On 2026-09-24, the full three-role Docker/Compose sequence in `scripts/smoke_test.py` also passed against isolated container volumes, including dependency stop/recovery and graceful shutdown. No live paid provider outage was induced; the model fault case uses a deterministic failing provider double after the same durable budget reservation.
