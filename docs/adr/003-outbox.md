# ADR-003: Outbox, fenced work leases, and completion-before-ACK

Status: accepted for v1. Date: 2026-09-16.

Database state and a broker publish cannot be committed atomically with an ordinary dual write. Insert business work and its event in one database transaction. Publish later, waiting for the broker acknowledgment before marking publication. Stable event IDs enable downstream deduplication but are not sufficient alone.

Long operations cannot keep a database transaction open across cloning and model requests. Claim a renewable lease, checkpoint idempotent batches, and atomically validate a monotonically increasing fencing token before writes. Final business results and consumer completion markers commit together, then ACK.

Never insert a permanent processed marker merely on receipt: a crash before work completes would lose progress. Never claim external model calls or charges are exactly once: uncertain provider calls may be billed and retried.

Consequence: leases/reconciliation add complexity, but allow observable recovery from process death. Fault tests target every database/publish/ACK gap and stale-writer race.
