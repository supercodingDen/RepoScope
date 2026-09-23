"""Real database and JetStream delivery crash-boundary acceptance."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import nats
import pytest
import pytest_asyncio

from contracts.models import IngestRequested
from reposcope.adapters.nats_delivery import JetStreamBroker
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.application.delivery import DeliveryWorker, OutboxPublisher
from reposcope.domain.delivery import Complete, Lease, LeaseLost, Outcome, PermanentFailure
from tests.integration.test_nats_recovery import _start_server, _stop_server, _wait_for_port
from tests.integration.test_work_persistence import DatabaseHarness, database, ingest, ready

pytestmark = pytest.mark.integration
__all__ = ["database"]


@pytest_asyncio.fixture
async def broker(tmp_path: Path) -> AsyncIterator[JetStreamBroker]:
    binary = os.environ.get("NATS_SERVER_BINARY")
    process = None
    if binary:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = int(listener.getsockname()[1])
        process = _start_server(Path(binary), port, tmp_path / "js")
        await _wait_for_port(port)
        url = f"nats://127.0.0.1:{port}"
    elif os.environ.get("RUN_INTEGRATION_TESTS") == "1":
        url = os.environ.get("NATS_URL", "nats://nats:4222")
    else:
        pytest.skip("Real broker integration requires explicit configuration")
    client = await nats.connect(url)
    # Separate stream AND subject namespace; never purge shared broker data.
    result = JetStreamBroker(client, namespace="test_" + uuid4().hex)
    try:
        await result.setup()
        yield result
    finally:
        await client.close()
        if process is not None:
            await asyncio.to_thread(_stop_server, process)


class Succeed:
    configured = True
    calls = 0

    async def handle(self, lease: Lease) -> Outcome:
        self.calls += 1
        return Complete()


async def event_for(db: DatabaseHarness) -> IngestRequested:
    cursor = await db.owner.execute("SELECT payload::text FROM reposcope.outbox_events LIMIT 1")
    row = await cursor.fetchone()
    assert row is not None
    return IngestRequested.model_validate_json(row[0])


@pytest.mark.asyncio
async def test_publish_ack_gap_and_completion_ack_gap_are_idempotent(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    await database.owner.execute("UPDATE reposcope.jobs SET status='queued'")
    repo = PostgresDeliveryRepository(database.pool)
    publisher = OutboxPublisher(repo, broker)
    claim = await repo.claim_outbox(uuid4())
    assert claim is not None
    await broker.publish(claim.event)
    await database.owner.execute(
        "UPDATE reposcope.outbox_events SET lease_until=now()-interval '1 second'"
    )
    assert await publisher.publish_one()
    with pytest.raises(LeaseLost):
        await repo.mark_published(claim)
    assert (await broker.client.jetstream().stream_info(broker.stream)).state.messages == 1
    message = await broker.fetch_one("indexer")
    assert message is not None
    event = await event_for(database)
    lease = await repo.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    await repo.finalize(lease, Complete())
    await message.nak(delay=0.01)
    await asyncio.sleep(0.03)
    duplicate = await broker.fetch_one("indexer")
    assert duplicate is not None
    handler = Succeed()
    await DeliveryWorker(repo, broker, "indexer", handler).process(duplicate)
    assert handler.calls == 0
    assert await repo.completed("indexer", event.event_id)
    assert (await broker.consumer_info("indexer")).num_ack_pending == 0
    cursor = await database.owner.execute(
        "SELECT count(*)::text FROM reposcope.delivery_completions"
    )
    assert await cursor.fetchone() == ("1",)


@pytest.mark.asyncio
async def test_expired_worker_cannot_heartbeat_checkpoint_or_finalize(
    database: DatabaseHarness,
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    await database.owner.execute("UPDATE reposcope.jobs SET status='queued'")
    repo = PostgresDeliveryRepository(database.pool)
    event = await event_for(database)
    old = await repo.claim(event, "indexer", uuid4())
    assert isinstance(old, Lease)
    await database.owner.execute(
        "UPDATE reposcope.consumer_work SET lease_until=now()-interval '1 second'"
    )
    new = await repo.claim(event, "indexer", uuid4())
    assert isinstance(new, Lease) and new.token > old.token
    with pytest.raises(LeaseLost):
        await repo.renew(old)
    async with database.pool.connection() as connection, connection.transaction():
        with pytest.raises(LeaseLost):
            await repo.lock_lease(connection, old)
    with pytest.raises(LeaseLost):
        await repo.finalize(old, Complete())
    await repo.finalize(new, Complete())


@pytest.mark.asyncio
async def test_concurrent_claims_and_permanent_failure(database: DatabaseHarness) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    event = await event_for(database)
    results = await asyncio.gather(*(repo.claim(event, "indexer", uuid4()) for _ in range(10)))
    leases = [value for value in results if isinstance(value, Lease)]
    assert len(leases) == 1
    await repo.finalize(leases[0], PermanentFailure("SOURCE_REJECTED"))
    cursor = await database.owner.execute("SELECT status,failure_code FROM reposcope.jobs")
    assert await cursor.fetchone() == ("failed", "SOURCE_REJECTED")


@pytest.mark.asyncio
async def test_invalid_and_forged_messages_quarantine_before_term(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    handler = Succeed()
    worker = DeliveryWorker(repo, broker, "indexer", handler)
    await broker.client.jetstream().publish(
        broker.subject("repo.ingest.requested"), b"password=private-question"
    )
    forged = (await event_for(database)).model_copy(update={"event_id": uuid4()})
    await broker.publish(forged)
    for _ in range(2):
        message = await broker.fetch_one("indexer")
        assert message is not None
        await worker.process(message)
    assert handler.calls == 0
    cursor = await database.owner.execute(
        "SELECT row_to_json(q)::text FROM reposcope.delivery_quarantine q"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 2 and all(
        "password" not in row[0] and "private-question" not in row[0] for row in rows
    )
    assert (await broker.consumer_info("indexer")).num_ack_pending == 0


@pytest.mark.asyncio
async def test_deadline_reconciles_never_delivered_and_exhausted_work(
    database: DatabaseHarness,
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    await database.owner.execute("UPDATE reposcope.jobs SET deadline_at=now()-interval '1 second'")
    assert await repo.reconcile() == 1
    cursor = await database.owner.execute("SELECT status,failure_code FROM reposcope.jobs")
    assert await cursor.fetchone() == ("failed", "DEADLINE_EXCEEDED")


@pytest.mark.asyncio
async def test_stage_deadline_promotes_safe_terminal_record(database: DatabaseHarness) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    event = await event_for(database)
    lease = await repo.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    async with repo.transaction() as connection:
        await repo.complete_stage(connection, lease)
    await database.owner.execute("UPDATE reposcope.jobs SET deadline_at=now()-interval '1 second'")
    assert await repo.reconcile() == 1
    cursor = await database.owner.execute(
        "SELECT outcome,failure_code FROM reposcope.delivery_completions"
    )
    assert await cursor.fetchone() == ("failed", "DEADLINE_EXCEEDED")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["renew", "finalize", "checkpoint"])
async def test_lease_expiring_while_waiting_for_unchanged_row_lock_cannot_write(
    database: DatabaseHarness, operation: str
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    event = await event_for(database)
    lease = await repo.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    await database.owner.execute(
        "UPDATE reposcope.consumer_work SET lease_until=clock_timestamp()+interval '0.2 second'"
    )
    await database.owner.execute(
        "UPDATE reposcope.jobs SET lease_until=clock_timestamp()+interval '0.2 second'"
    )

    async def operation_under_test() -> None:
        if operation == "renew":
            await repo.renew(lease)
        elif operation == "finalize":
            await repo.finalize(lease, PermanentFailure("TEST_FAILURE"))
        else:
            async with repo.transaction() as connection:
                await repo.lock_lease(connection, lease)

    async with database.owner.transaction():
        await database.owner.execute("SELECT job_id FROM reposcope.jobs FOR UPDATE")
        task = asyncio.create_task(operation_under_test())
        await asyncio.sleep(0.35)
    with pytest.raises(LeaseLost):
        await task
    assert not await repo.completed("indexer", event.event_id)


@pytest.mark.asyncio
async def test_outbox_expiring_during_lock_wait_cannot_mark_published(
    database: DatabaseHarness,
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    claim = await repo.claim_outbox(uuid4())
    assert claim is not None
    await database.owner.execute(
        "UPDATE reposcope.outbox_events SET lease_until=clock_timestamp()+interval '0.2 second'"
    )
    async with database.owner.transaction():
        await database.owner.execute("SELECT event_id FROM reposcope.outbox_events FOR UPDATE")
        task = asyncio.create_task(repo.mark_published(claim))
        await asyncio.sleep(0.35)
    with pytest.raises(LeaseLost):
        await task
    cursor = await database.owner.execute(
        "SELECT count(*)::text FROM reposcope.outbox_events WHERE published_at IS NULL"
    )
    assert await cursor.fetchone() == ("1",)


class Retry:
    configured = True

    async def handle(self, lease: Lease) -> Outcome:
        from reposcope.domain.delivery import TransientFailure

        return TransientFailure("DEPENDENCY_UNAVAILABLE")


@pytest.mark.asyncio
async def test_transient_retry_is_durable_and_does_not_reset_attempts(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    await OutboxPublisher(repo, broker).publish_one()
    message = await broker.fetch_one("indexer")
    assert message is not None
    await DeliveryWorker(repo, broker, "indexer", Retry()).process(message)
    event = await event_for(database)
    assert await repo.claim(event, "indexer", uuid4()) is None
    cursor = await database.owner.execute(
        "SELECT status,attempts::text,(next_attempt_at>clock_timestamp())::text FROM reposcope.jobs"
    )
    assert await cursor.fetchone() == ("queued", "1", "true")
    await database.owner.execute(
        "UPDATE reposcope.consumer_work SET next_attempt_at=now()-interval '1 second'"
    )
    lease = await repo.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease) and lease.attempt == 2
    await repo.release(lease, 0)
    await database.owner.execute("UPDATE reposcope.jobs SET attempts=5")
    assert await repo.reconcile() == 1
    cursor = await database.owner.execute("SELECT failure_code FROM reposcope.jobs")
    assert await cursor.fetchone() == ("ATTEMPTS_EXHAUSTED",)


class Blocking:
    configured = True

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def handle(self, lease: Lease) -> Outcome:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        return Complete()


@pytest.mark.asyncio
async def test_shutdown_cancels_work_without_terminal_failure(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    await OutboxPublisher(repo, broker).publish_one()
    message = await broker.fetch_one("indexer")
    assert message is not None
    handler = Blocking()
    task = asyncio.create_task(DeliveryWorker(repo, broker, "indexer", handler).process(message))
    await handler.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert handler.cancelled.is_set()
    cursor = await database.owner.execute(
        "SELECT status,coalesce(failure_code,'') FROM reposcope.jobs"
    )
    assert await cursor.fetchone() == ("queued", "")
    assert not await repo.completed("indexer", (await event_for(database)).event_id)
    assert (await broker.consumer_info("indexer")).num_ack_pending == 1


@pytest.mark.asyncio
async def test_failed_heartbeat_cancels_external_work_and_does_not_ack(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    from reposcope.domain.delivery import DeliveryPolicy

    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool, DeliveryPolicy(heartbeat_seconds=1))
    await OutboxPublisher(repo, broker).publish_one()
    message = await broker.fetch_one("indexer")
    assert message is not None
    handler = Blocking()
    task = asyncio.create_task(DeliveryWorker(repo, broker, "indexer", handler).process(message))
    await handler.started.wait()
    await database.owner.execute(
        "UPDATE reposcope.consumer_work SET lease_until=now()-interval '1 second'"
    )
    await asyncio.wait_for(task, 3)
    assert handler.cancelled.is_set()
    assert (await broker.consumer_info("indexer")).num_ack_pending == 1
    assert not await repo.completed("indexer", (await event_for(database)).event_id)


@pytest.mark.asyncio
async def test_unconfigured_handler_defers_without_consuming_attempts(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    from reposcope.domain.delivery import UnconfiguredHandler

    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    await OutboxPublisher(repo, broker).publish_one()
    message = await broker.fetch_one("indexer")
    assert message is not None
    await DeliveryWorker(repo, broker, "indexer", UnconfiguredHandler()).process(message)
    cursor = await database.owner.execute("SELECT status,attempts::text FROM reposcope.jobs")
    assert await cursor.fetchone() == ("queued", "0")
    cursor = await database.owner.execute("SELECT count(*)::text FROM reposcope.consumer_work")
    assert await cursor.fetchone() == ("0",)


@pytest.mark.asyncio
async def test_broker_delivery_ceiling_has_finite_database_failure(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    from reposcope.domain.delivery import DeliveryPolicy

    limited = JetStreamBroker(broker.client, DeliveryPolicy(max_deliver=2), "limit_" + uuid4().hex)
    await limited.setup()
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    await OutboxPublisher(repo, limited).publish_one()
    for _ in range(2):
        message = await limited.fetch_one("indexer")
        assert message is not None
        await message.nak()
        await broker.client.flush()
    assert await limited.fetch_one("indexer") is None
    await database.owner.execute("UPDATE reposcope.jobs SET deadline_at=now()-interval '1 second'")
    assert await repo.reconcile() == 1
    assert await repo.completed("indexer", (await event_for(database)).event_id)


@pytest.mark.asyncio
async def test_completion_transaction_failure_rolls_back_without_ack(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    await database.owner.execute("UPDATE reposcope.jobs SET status='queued'")
    repo = PostgresDeliveryRepository(database.pool)
    await OutboxPublisher(repo, broker).publish_one()
    await database.owner.execute(
        "CREATE FUNCTION reposcope.reject_completion() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'test'; END $$"
    )
    await database.owner.execute(
        "CREATE TRIGGER reject_completion BEFORE INSERT ON reposcope.delivery_completions FOR "
        "EACH ROW EXECUTE FUNCTION reposcope.reject_completion()"
    )
    try:
        message = await broker.fetch_one("indexer")
        assert message is not None
        await DeliveryWorker(repo, broker, "indexer", Succeed()).process(message)
        assert not await repo.completed("indexer", (await event_for(database)).event_id)
        cursor = await database.owner.execute("SELECT status FROM reposcope.jobs")
        assert await cursor.fetchone() == ("queued",)
        assert (await broker.consumer_info("indexer")).num_ack_pending == 1
    finally:
        await database.owner.execute(
            "DROP TRIGGER reject_completion ON reposcope.delivery_completions"
        )
        await database.owner.execute("DROP FUNCTION reposcope.reject_completion()")


@pytest.mark.asyncio
async def test_publication_waits_for_business_commit(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    repo = PostgresDeliveryRepository(database.pool)
    async with database.owner.transaction():
        await database.owner.execute("SELECT singleton FROM reposcope.admission_lock FOR UPDATE")
        submission = asyncio.create_task(ingest(database))
        await asyncio.sleep(0.05)
        assert not await OutboxPublisher(repo, broker).publish_one()
        assert (await broker.client.jetstream().stream_info(broker.stream)).state.messages == 0
    await submission
    assert await OutboxPublisher(repo, broker).publish_one()
    message = await broker.fetch_one("indexer")
    assert message is not None
    assert await repo.authorized(IngestRequested.model_validate_json(message.data))


@pytest.mark.asyncio
async def test_repeated_orderly_shutdown_preserves_last_attempt(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    await database.owner.execute("UPDATE reposcope.jobs SET attempts=4")
    await OutboxPublisher(repo, broker).publish_one()
    for _ in range(3):
        message = await broker.fetch_one("indexer")
        assert message is not None
        handler = Blocking()
        task = asyncio.create_task(
            DeliveryWorker(repo, broker, "indexer", handler).process(message)
        )
        await handler.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await repo.reconcile() == 0
        cursor = await database.owner.execute("SELECT attempts::text,status FROM reposcope.jobs")
        assert await cursor.fetchone() == ("4", "queued")
        await database.owner.execute(
            "UPDATE reposcope.consumer_work SET next_attempt_at=now()-interval '1 second'"
        )
        await message.nak()
        await broker.client.flush()


@pytest.mark.asyncio
async def test_duplicate_publish_outside_broker_dedup_still_executes_once(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    await database.owner.execute("UPDATE reposcope.jobs SET status='queued'")
    repo = PostgresDeliveryRepository(database.pool)
    event = await event_for(database)
    # Omit broker dedup header to exercise a persisted duplicate, as after window expiry.
    for _ in range(2):
        await broker.client.jetstream().publish(
            broker.subject(event.event_type), event.model_dump_json().encode()
        )
    handler = Succeed()
    worker = DeliveryWorker(repo, broker, "indexer", handler)
    for _ in range(2):
        message = await broker.fetch_one("indexer")
        assert message is not None
        await worker.process(message)
    assert handler.calls == 1
    assert (await broker.consumer_info("indexer")).num_ack_pending == 0


@pytest.mark.asyncio
async def test_stream_drift_is_rejected_without_mutating_existing_resources(
    broker: JetStreamBroker,
) -> None:
    from dataclasses import replace

    configured = await broker.client.jetstream().stream_info(broker.stream)
    await broker.client.jetstream().update_stream(replace(configured.config, max_bytes=1024 * 1024))
    with pytest.raises(RuntimeError, match="configuration drift"):
        await broker.setup()
    actual = await broker.client.jetstream().stream_info(broker.stream)
    assert actual.config.max_bytes == 1024 * 1024


@pytest.mark.asyncio
async def test_agent_delivery_attempts_are_separate_and_result_is_atomic(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    from contracts.models import AgentRequested, RunAccepted, RunResult

    accepted = await ingest(database)
    await ready(database, accepted)
    response = await database.client.post(
        "/v1/runs",
        json={"repository_id": str(accepted.repository_id), "question": "fixture question"},
        headers={"Idempotency-Key": "agent-delivery"},
    )
    run = RunAccepted.model_validate_json(response.content)
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s", (run.run_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    event = AgentRequested.model_validate_json(row[0])
    repo = PostgresDeliveryRepository(database.pool)
    assert await repo.authorized(event)
    lease = await repo.claim(event, "agent", uuid4())
    assert isinstance(lease, Lease)
    cursor = await database.owner.execute(
        "SELECT attempts::text,delivery_attempts::text FROM reposcope.agent_runs"
    )
    assert await cursor.fetchone() == ("0", "1")
    result = RunResult(
        answer="Insufficient evidence.",
        citations=[],
        evidence_status="insufficient",
        model="mock",
        estimated_cost_usd="0.000000",
    )
    await repo.finalize(lease, Complete(result))
    await broker.publish(event)
    message = await broker.fetch_one("agent")
    assert message is not None
    handler = Succeed()
    await DeliveryWorker(repo, broker, "agent", handler).process(message)
    assert handler.calls == 0
    cursor = await database.owner.execute("SELECT status,result::text FROM reposcope.agent_runs")
    row = await cursor.fetchone()
    assert (
        row is not None
        and row[0] == "succeeded"
        and RunResult.model_validate_json(row[1]) == result
    )
    assert (await broker.consumer_info("agent")).num_ack_pending == 0


class UncommittedStage:
    configured = True

    async def handle(self, lease: Lease) -> Outcome:
        from reposcope.domain.delivery import Staged

        return Staged()


@pytest.mark.asyncio
async def test_handler_staged_flag_is_not_accepted_as_completion_proof(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    await ingest(database)
    repo = PostgresDeliveryRepository(database.pool)
    await OutboxPublisher(repo, broker).publish_one()
    message = await broker.fetch_one("indexer")
    assert message is not None
    await DeliveryWorker(repo, broker, "indexer", UncommittedStage()).process(message)
    assert (await broker.consumer_info("indexer")).num_ack_pending == 1
    assert not await repo.completed("indexer", (await event_for(database)).event_id)


@pytest.mark.asyncio
async def test_quarantine_failure_does_not_terminate_message(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    repo = PostgresDeliveryRepository(database.pool)
    await broker.client.jetstream().publish(
        broker.subject("repo.ingest.requested"), b"unsafe fixture"
    )
    message = await broker.fetch_one("indexer")
    assert message is not None
    await database.owner.execute(
        "CREATE FUNCTION reposcope.reject_quarantine() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'test'; END $$"
    )
    await database.owner.execute(
        "CREATE TRIGGER reject_quarantine BEFORE INSERT ON reposcope.delivery_quarantine "
        "FOR EACH ROW EXECUTE FUNCTION reposcope.reject_quarantine()"
    )
    try:
        from psycopg.errors import RaiseException

        with pytest.raises(RaiseException):
            await DeliveryWorker(repo, broker, "indexer", Succeed()).process(message)
        assert (await broker.consumer_info("indexer")).num_ack_pending == 1
    finally:
        await database.owner.execute(
            "DROP TRIGGER reject_quarantine ON reposcope.delivery_quarantine"
        )
        await database.owner.execute("DROP FUNCTION reposcope.reject_quarantine()")


class ConcurrentBlocking:
    configured = True

    def __init__(self) -> None:
        self.started = 0
        self.active = 0
        self.maximum = 0
        self.two_started = asyncio.Event()

    async def handle(self, lease: Lease) -> Outcome:
        self.started += 1
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        if self.active == 2:
            self.two_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.active -= 1
        return Complete()


@pytest.mark.asyncio
async def test_worker_loop_bounds_concurrency_and_drains_cancellation(
    database: DatabaseHarness, broker: JetStreamBroker
) -> None:
    repo = PostgresDeliveryRepository(database.pool)
    publisher = OutboxPublisher(repo, broker)
    for index in range(3):
        await ingest(database, f"parallel-{index}")
        assert await publisher.publish_one()
    handler = ConcurrentBlocking()
    worker = DeliveryWorker(repo, broker, "indexer", handler)
    stopping = asyncio.Event()
    task = asyncio.create_task(worker.run(stopping))
    await asyncio.wait_for(handler.two_started.wait(), 5)
    await asyncio.sleep(0.05)
    assert handler.started == 2 and handler.maximum == 2
    stopping.set()
    await asyncio.wait_for(task, 5)
    assert handler.active == 0
    cursor = await database.owner.execute(
        "SELECT count(*)::text FROM reposcope.jobs WHERE status='queued' AND attempts=0"
    )
    assert await cursor.fetchone() == ("3",)
