# ADR-001: Use NATS JetStream for durable work

Status: accepted for v1. Date: 2026-09-16.

The platform needs durable queued work, acknowledgment/redelivery, independent consumers, replay, and bounded in-flight work on a single development host. JetStream meets these needs with fewer operating components than a Kafka deployment. Redis is not the task source of truth and FastAPI BackgroundTasks is not a durable queue.

Use separate durable pull consumers for ingestion and agent work. Persist events through transactional outbox; use application-level deduplication and fencing. Delivery is at least once, not end-to-end exactly once. Configure maximum delivery, stream limits, and reconcilers explicitly.

Consequence: the project owns leases, retries, failure visibility, and transactional correctness. Reconsider Kafka for long-lived high-volume event logs, partitioned stream processing, or an existing Kafka operating environment.

Reference: [NATS delivery and acknowledgment](https://docs.nats.io/learn/jetstream/delivery-and-acknowledgment).
