# Contract and reliability semantics

Canonical schemas are exported from contracts/models.py. Schema version 1 rejects unknown fields. Semantic validators additionally enforce source containment, matching snapshot IDs, line ordering, and state/result consistency; these checks are not all expressible in generated JSON Schema. Do not replace runtime validation with schema shape checks alone.

## API conventions

- Public business endpoints require an Authorization bearer deployment token. Map the token to a stable server-owned principal; do not trust caller-supplied principal IDs. A first-party single-owner demo can use one principal. Future tenancy requires a separate reviewed design.
- POST /v1/repositories and POST /v1/runs require Idempotency-Key, 1-128 printable non-space ASCII characters. Scope by principal and route. Hash canonical validated request JSON, not original whitespace. Same key/hash replays the original status/body; changed hash returns 409. In-flight races are serialized by a DB unique constraint.
- Keep keys for at least 7 days and until the corresponding task terminates. After expiry, reuse can create new work and is documented as such.
- A request-specific UUID is returned as X-Request-ID. Do not accept arbitrary unbounded caller correlation IDs. Time fields use timezone-aware RFC3339; IDs use UUID strings.
- Successful task creation returns 202. A failed background task is a successful GET with status=failed and a safe failure_code, not an HTTP 500 for status polling.
- Bound request bodies to 64 KiB at ingress and application boundaries; return a problem body on application-controlled errors. An upstream proxy must use an equivalent JSON error template where feasible.
- POST /v1/search creates a short-lived query-budget reservation in live mode, because query embeddings are paid too. It is not a free endpoint merely because it avoids generation.

## State machines

| Object | Allowed transitions | Rule |
| --- | --- | --- |
| Job/run | queued → running; running → succeeded/failed; queued → failed | Admission failure creates no job; shutdown alone is not terminal failure |
| Retryable work | running → queued | Persist next_attempt_at and attempt count before rescheduling |
| Generation | staged → ready/failed/superseded | Only a ready generation may become active; an older request cannot replace a newer target |
| Consumer work | available → leased → completed | Only current unexpired fenced lease may checkpoint or finalize |
| Reservation | reserved → settled/uncertain/released | A potentially billed timeout is uncertain, not a free retry |

SSE run.started can occur again after recovery. Persisted sequence numbers disambiguate attempts; clients deduplicate by run/sequence. A restarted agent may recompute from a bounded evidence checkpoint but retains total model-attempt and budget counters. Never promise bit-identical agent answers across retries.

## Outbox and lease protocol

1. Request transaction inserts authoritative business work and its outbox event together.
2. Publisher claims an event in a short transaction, publishes with a stable ID, waits for JetStream acknowledgment, then marks it published. A crash in the last gap causes a duplicate publish; consumer idempotency covers it.
3. Consumer obtains a 60-second lease and increments a fencing token, renewed every 15 seconds. Batch/final writes atomically check the current token in the same transaction, using a row lock or equivalent atomic conditional operation. A read-then-write check outside the transaction is insufficient.
4. The worker does source/model I/O outside long transactions. It checkpoints bounded batches and emits NATS in-progress signals. Broker progress signals do not establish database ownership.
5. Final business state, final event, and consumer completion commit atomically. Only then ACK. A duplicate completed event is ACKed without reapplying results.
6. Retry transient failures with jittered backoff (base 1 second, cap 30 seconds), at most 5 handler attempts, under an overall deadline. Set an explicit broker delivery ceiling and reconcile its exhaustion with DB state; do not assume JetStream automatically creates a DLQ.
7. A reconciler examines expired leases and stuck outbox work every 30 seconds. Invalid event schemas are quarantined with a safe fingerprint and durable failure record; never dump secret-bearing arbitrary event bytes.

Ingestion events include a requested reference; resolution pins the first commit on the durable job. Agent events already contain the selected generation and commit. Events carry IDs and policy version, not full source, prompts, tokens, or API keys.

Consumers reload authoritative job/run records and verify payload scope, principal, and revision against those records before processing. A correctly shaped broker event is not itself authorization. Runtime token limits and filesystem containment checks remain mandatory even after wire validation.

## Error mapping

| HTTP | Codes | Expected action |
| --- | --- | --- |
| 405 | METHOD_NOT_ALLOWED | Reject an unsupported HTTP method and return the Allow header |
| 401 | UNAUTHENTICATED | Reject missing or invalid credentials |
| 403 | FORBIDDEN | Reject a disallowed resource/action |
| 404 | NOT_FOUND | Resource absent or intentionally hidden |
| 409 | IDEMPOTENCY_CONFLICT; INDEX_NOT_READY | Correct request or wait for indexing |
| 410 | EVENT_CURSOR_EXPIRED | Fetch current run state; replay history expired |
| 413 | PAYLOAD_TOO_LARGE | Reduce request body |
| 422 | VALIDATION_ERROR | Correct invalid typed arguments |
| 429 | RATE_LIMITED; BUDGET_EXCEEDED | Respect Retry-After or revise operator budget |
| 503 | DEPENDENCY_UNAVAILABLE; PROVIDER_UNAVAILABLE | Bounded retry; no silent model escalation |
| 504 | PROVIDER_TIMEOUT | Safe timeout response; preserve uncertain spend |
| 500 | INTERNAL_ERROR | Generic client message; sanitized internal diagnostic |

The problem body contains type, title, status, detail, code, and request_id. Pydantic validation errors must be mapped instead of exposing its default raw request/body details. Workers classify transient/permanent/cancellation separately and log a single structured boundary error.

## SSE

Authenticate before sending headers. Each frame uses id=<sequence>, event=<data.kind>, and data=<RunEvent JSON>. Send a comment heartbeat every 15 seconds. Last-Event-ID is a positive decimal integer; a future cursor returns 422. An expired nonzero cursor returns 410 before headers. A missing cursor starts from retained beginning; for a terminal run beyond retention, return 410 and direct the client to its persisted result.

Replay committed events in order and then tail new commits. A DB sequence allocation/insert transaction prevents missing cursor gaps being mistaken for committed data. Slow-client buffers contain at most 64 events; disconnect slow clients without cancelling the durable run. Disconnect is not task cancellation. A failure after headers is a run.failed event when durable storage is available; a connection failure alone does not fabricate a persisted terminal event.

## Internal contracts

The two workers expose private health, readiness, and metrics only. internal.yaml describes this management plane. Retrieval is an in-process typed service shared by API and agent; there is no private retrieval HTTP contract to drift. Agent tool JSON schemas are exported separately, with a server-pinned scope and bounded outputs.
