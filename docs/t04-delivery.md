# Durable delivery (T04)

HTTP admission commits business state, the replay response and an outbox event in one PostgreSQL transaction. The API role's publisher claims a short lease, publishes outside that transaction, waits for a JetStream publication acknowledgment, then marks the event published using its fencing token. Event IDs are stable across retries.

The file-backed stream uses bounded retention and two durable request consumers with explicit acknowledgment. The indexer receives `repo.ingest.requested`; the agent receives `agent.run.requested`. Source continuations are retained on a separate subject without being mistaken for new acquisition requests. Startup accepts only the reviewed topology, including the known additive T04-to-T05 subject upgrade; other configuration drift fails startup.

Consumers validate and authorize events against authoritative outbox/business state before claiming work. A lease expires after 60 seconds and is renewed every 15 seconds, with progress acknowledgments. Work runs outside database transactions with at most two handlers per role. Heartbeat loss cancels the handler; stale workers cannot checkpoint or finalize. Orderly cancellation releases its claim without spending another handler attempt.

Completion is committed before broker acknowledgment. Redelivery after that commit acknowledges the prior result without running the handler again. Staged completion requires a durable checkpoint and continuation in the same fenced transaction. Unconfigured handlers defer work without falsely reporting success or consuming handler attempts.

Retries are bounded by durable attempt counts and the original business deadline. Reconciliation covers never-delivered messages and broker delivery exhaustion. Malformed or forged messages are quarantined using a fingerprint and safe reason, without retaining their raw content. Broker deduplication is an optimization; database fencing and completion records provide committed-output idempotency.

Evidence: `tests/integration/test_delivery.py` exercises real PostgreSQL and NATS crash gaps, duplicate delivery, expiry while waiting for locks, stale fencing, retry limits, cancellation, quarantine and staged completion. Historical T04 verification is recorded in `docs/verification/t04-delivery-checks.txt`; repeat the complete regression suite after subsequent changes.

T04 does not execute agent model calls or make an index ready. Those handlers belong to later milestones. No paid provider is enabled by durable message handling.
