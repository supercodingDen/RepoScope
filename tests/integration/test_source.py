"""Actual PostgreSQL fencing and source-stage transaction acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg import OperationalError
from psycopg.errors import CheckViolation

from contracts.models import SourceAcquired
from reposcope.adapters.embedding import MockEmbeddingProvider
from reposcope.adapters.nats_delivery import JetStreamBroker
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.adapters.postgres_index import PostgresIndexRepository
from reposcope.adapters.postgres_source import PostgresSourceRepository
from reposcope.adapters.source_git import GitSource
from reposcope.adapters.source_storage import SnapshotBuilder, SourceStore
from reposcope.application.delivery import DeliveryWorker, OutboxPublisher
from reposcope.application.index import IndexHandler
from reposcope.application.source import SourceAcquisitionHandler
from reposcope.domain.delivery import Lease, LeaseLost, Outcome, Staged, TransientFailure
from reposcope.domain.source import SourceLimits, SourceRejected
from reposcope.domain.source_snapshot import SourceManifest, SourceSnapshot
from tests.integration.test_delivery import broker, event_for
from tests.integration.test_work_persistence import DatabaseHarness, database, ingest

pytestmark = pytest.mark.integration
__all__ = ["database", "broker"]


@pytest.mark.asyncio
async def test_source_pin_is_compare_and_set(database: DatabaseHarness) -> None:
    await ingest(database)
    delivery = PostgresDeliveryRepository(database.pool)
    repository = PostgresSourceRepository(delivery)
    event = await event_for(database)
    lease = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    request = await repository.prepare(lease)
    assert request.commit_sha is None
    values = await asyncio.gather(repository.pin(lease, "a" * 40), repository.pin(lease, "b" * 40))
    assert values[0] == values[1]
    await delivery.release(lease, 0)
    newer = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(newer, Lease)
    assert (await repository.prepare(newer)).commit_sha == values[0]
    with pytest.raises(LeaseLost):
        await repository.pin(lease, "c" * 40)


@pytest.mark.asyncio
async def test_source_stage_is_atomic_and_fenced(database: DatabaseHarness) -> None:
    await ingest(database)
    delivery = PostgresDeliveryRepository(database.pool)
    repository = PostgresSourceRepository(delivery)
    event = await event_for(database)
    lease = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    await repository.prepare(lease)
    commit = await repository.pin(lease, "a" * 40)
    manifest = SourceManifest((await repository.prepare(lease)).url, commit, (), {}, 0, 0, ())
    snapshot = SourceSnapshot(
        manifest, f"snapshots/{event.aggregate_id}-{lease.token}/{manifest.digest}"
    )
    await database.owner.execute(
        "ALTER TABLE reposcope.outbox_events ADD CONSTRAINT injected_source_failure CHECK "
        "(event_type <> 'repo.source.acquired')"
    )
    with pytest.raises(CheckViolation):
        await repository.stage(lease, snapshot)
    assert not await delivery.completed("indexer", event.event_id)
    cursor = await database.owner.execute("SELECT count(*)::text FROM reposcope.source_manifests")
    assert await cursor.fetchone() == ("0",)
    await database.owner.execute(
        "ALTER TABLE reposcope.outbox_events DROP CONSTRAINT injected_source_failure"
    )
    await repository.stage(lease, snapshot)
    assert await delivery.completed("indexer", event.event_id)
    cursor = await database.owner.execute(
        "SELECT j.status,j.progress_percent::text,g.status FROM reposcope.jobs j JOIN "
        "reposcope.index_generations g USING(generation_id)"
    )
    assert await cursor.fetchone() == ("running", "20", "staged")
    with pytest.raises(LeaseLost):
        await repository.stage(lease, snapshot)
    assert await delivery.reconcile() == 0


@pytest.mark.asyncio
async def test_last_attempt_stage_survives_reconciliation(database: DatabaseHarness) -> None:
    await ingest(database)
    await database.owner.execute("UPDATE reposcope.jobs SET attempts=4")
    delivery = PostgresDeliveryRepository(database.pool)
    source = PostgresSourceRepository(delivery)
    event = await event_for(database)
    lease = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease) and lease.attempt == 5
    request = await source.prepare(lease)
    commit = await source.pin(lease, "a" * 40)
    manifest = SourceManifest(request.url, commit, (), {}, 0, 0, ())
    snapshot = SourceSnapshot(
        manifest, f"snapshots/{event.aggregate_id}-{lease.token}/{manifest.digest}"
    )
    await source.stage(lease, snapshot)
    assert await delivery.reconcile() == 0
    await database.owner.execute(
        "UPDATE reposcope.outbox_events SET published_at=now() WHERE "
        "event_type='repo.ingest.requested'"
    )
    claim = await delivery.claim_outbox(uuid4())
    assert claim is not None and claim.event.event_type == "repo.source.acquired"
    await database.owner.execute("UPDATE reposcope.jobs SET deadline_at=now()-interval '1 second'")
    assert await delivery.reconcile() == 1
    cursor = await database.owner.execute("SELECT count(*)::text FROM reposcope.source_manifests")
    assert await cursor.fetchone() == ("1",)


@pytest.mark.asyncio
async def test_terminal_crash_orphan_cleanup(database: DatabaseHarness, tmp_path: Path) -> None:
    await ingest(database)
    delivery = PostgresDeliveryRepository(database.pool)
    source = PostgresSourceRepository(delivery)
    event = await event_for(database)
    lease = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    await source.prepare(lease)
    store = SourceStore(tmp_path / "store")
    attempt = store.attempt(event.aggregate_id, lease.token)
    (attempt / "partial").write_text("owned partial file")
    assert await source.cleanup_candidates() == ()
    await database.owner.execute("UPDATE reposcope.jobs SET deadline_at=now()-interval '1 second'")
    assert await delivery.reconcile() == 1
    assert await source.cleanup_candidates() == ((event.aggregate_id, lease.token),)
    store.cleanup(attempt)
    await source.cleaned(event.aggregate_id, lease.token)
    assert not attempt.exists()
    assert await source.cleanup_candidates() == ()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("REPOSCOPE_TEST_PUBLIC_SOURCE") != "1",
    reason="Explicit real public-source acceptance",
)
async def test_api_broker_public_source_stage_handoff(
    database: DatabaseHarness, broker: JetStreamBroker, tmp_path: Path
) -> None:
    response = await database.client.post(
        "/v1/repositories",
        headers={"Idempotency-Key": "real-source"},
        json={"url": "https://github.com/pallets/itsdangerous"},
    )
    assert response.status_code == 202
    delivery = PostgresDeliveryRepository(database.pool)
    source = PostgresSourceRepository(delivery)
    backend = GitSource(Path(os.environ["REPOSCOPE_GIT_BINARY"]), SourceStore(tmp_path / "store"))

    class CountingHandler(SourceAcquisitionHandler):
        calls = 0

        async def handle(self, lease: Lease) -> Outcome:
            self.calls += 1
            return await super().handle(lease)

    handler = CountingHandler(source, backend)
    publisher = OutboxPublisher(delivery, broker)
    worker = DeliveryWorker(delivery, broker, "indexer", handler)
    assert await publisher.publish_one()
    message = await broker.fetch_one("indexer")
    assert message is not None
    await worker.process(message)
    event = await event_for(database)
    assert await delivery.completed("indexer", event.event_id)
    cursor = await database.owner.execute(
        "SELECT "
        "j.status,j.progress_percent::text,length(j.commit_sha)::text,m.manifest_digest FROM "
        "reposcope.jobs j JOIN reposcope.source_manifests m USING(job_id)"
    )
    row = await cursor.fetchone()
    assert row is not None and row[:3] == ("running", "20", "40")
    assert await publisher.publish_one()
    continuation = await broker.client.jetstream().get_last_msg(
        broker.stream, broker.subject("repo.source.acquired")
    )
    assert continuation.data is not None
    acquired = SourceAcquired.model_validate_json(continuation.data)
    assert acquired.payload.manifest_digest == row[3]
    assert acquired.payload.job_id == event.aggregate_id
    assert acquired.payload.repository_id == event.payload.repository_id
    assert acquired.payload.principal_id == event.payload.principal_id
    cursor = await database.owner.execute(
        "SELECT storage_key,commit_sha FROM reposcope.source_manifests"
    )
    stored = await cursor.fetchone()
    assert stored is not None and stored[1] == acquired.payload.commit_sha
    manifest_bytes = (backend.store.root / stored[0] / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == acquired.payload.manifest_digest
    assert list((backend.store.root / "attempts").iterdir()) == []
    await broker.client.jetstream().publish(
        broker.subject(event.event_type), event.model_dump_json().encode()
    )
    duplicate = await broker.fetch_one("indexer")
    assert duplicate is not None
    await worker.process(duplicate)
    assert handler.calls == 1
    cursor = await database.owner.execute("SELECT count(*)::text FROM reposcope.source_manifests")
    assert await cursor.fetchone() == ("1",)
    assert await source.cleanup_candidates() == ()
    index_worker = DeliveryWorker(
        delivery,
        broker,
        "source",
        IndexHandler(PostgresIndexRepository(delivery), backend.store, MockEmbeddingProvider()),
    )
    source_message = await broker.fetch_one("source")
    assert source_message is not None
    await index_worker.process(source_message)
    assert await delivery.completed("source", acquired.event_id)
    cursor = await database.owner.execute(
        "SELECT j.status,g.status,r.active_generation_id::text "
        "FROM reposcope.jobs j JOIN reposcope.index_generations g "
        "ON g.generation_id=j.generation_id "
        "JOIN reposcope.repositories r ON r.repository_id=j.repository_id"
    )
    assert await cursor.fetchone() == ("succeeded", "ready", str(acquired.payload.generation_id))
    cursor = await database.owner.execute(
        "SELECT count(*)::text FROM reposcope.index_chunks WHERE generation_id=%s",
        (acquired.payload.generation_id,),
    )
    indexed = await cursor.fetchone()
    assert indexed is not None and int(indexed[0]) > 0


class _MovingSource:
    """A source-port fixture that changes its ref between durable worker retries."""

    def __init__(self, store: SourceStore) -> None:
        self.store = store
        self.current = "a" * 40
        self.resolutions = 0
        self.acquisitions = 0
        self.commits: list[str] = []

    def cleanup_obsolete(self, job_id: UUID, tokens: tuple[int, ...]) -> None:
        for token in tokens:
            self.store.cleanup(self.store.root / "attempts" / f"{job_id}-{token}")
            self.store.cleanup_snapshot_attempt(job_id, token)

    @contextmanager
    def session(
        self, url: str, job_id: UUID, token: int, limits: SourceLimits, stop: threading.Event
    ) -> Iterator[_FixtureSession]:
        attempt = self.store.attempt(job_id, token)
        try:
            yield _FixtureSession(self, url, job_id, attempt, limits)
        finally:
            self.store.cleanup(attempt)


class _FixtureSession:
    def __init__(
        self, source: _MovingSource, url: str, job_id: UUID, attempt: Path, limits: SourceLimits
    ) -> None:
        self.source = source
        self.url = url
        self.job_id = job_id
        self.attempt = attempt
        self.limits = limits

    def resolve(self, reference: str) -> str:
        self.source.resolutions += 1
        return self.source.current

    def acquire(self, commit: str) -> SourceSnapshot:
        self.source.acquisitions += 1
        self.source.commits.append(commit)
        if self.source.acquisitions == 1:
            raise SourceRejected("SOURCE_NETWORK_FAILED")
        builder = SnapshotBuilder(self.attempt, self.limits)
        assert builder.path("fixture.py")
        builder.add("fixture.py", b"answer = 42\n")
        return self.source.store.finalize(
            self.attempt, self.job_id, builder.manifest(self.url, commit)
        )


@pytest.mark.asyncio
async def test_moving_reference_retry_reuses_pinned_commit(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    await ingest(database)
    delivery = PostgresDeliveryRepository(database.pool)
    source = PostgresSourceRepository(delivery)
    backend = _MovingSource(SourceStore(tmp_path / "store"))
    handler = SourceAcquisitionHandler(source, backend)
    event = await event_for(database)
    lease = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    assert isinstance(await handler.handle(lease), TransientFailure)
    assert (await source.prepare(lease)).commit_sha == "a" * 40
    backend.current = "b" * 40
    await delivery.release(lease, 0)
    retry = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(retry, Lease)
    assert isinstance(await handler.handle(retry), Staged)
    assert backend.resolutions == 1
    assert backend.commits == ["a" * 40, "a" * 40]


@pytest.mark.asyncio
async def test_crash_after_files_before_database_recovers(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    await ingest(database)
    delivery = PostgresDeliveryRepository(database.pool)
    source = PostgresSourceRepository(delivery)
    backend = _MovingSource(SourceStore(tmp_path / "store"))
    backend.acquisitions = 1
    event = await event_for(database)
    lease = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    request = await source.prepare(lease)
    commit = await source.pin(lease, "a" * 40)
    with backend.session(
        request.url, event.aggregate_id, lease.token, SourceLimits(), threading.Event()
    ) as session:
        orphan = session.acquire(commit)
    assert (backend.store.root / orphan.storage_key).exists()
    await database.owner.execute(
        "UPDATE reposcope.consumer_work SET lease_until=now()-interval '1 second'"
    )
    retry = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(retry, Lease)
    with pytest.raises(LeaseLost):
        await source.stage(lease, orphan)
    assert isinstance(await SourceAcquisitionHandler(source, backend).handle(retry), Staged)
    assert not (backend.store.root / orphan.storage_key).exists()
    cursor = await database.owner.execute("SELECT manifest_digest FROM reposcope.source_manifests")
    assert await cursor.fetchone() == (orphan.digest,)


@pytest.mark.asyncio
async def test_cleanup_filesystem_failure_remains_retryable(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    await ingest(database)
    delivery = PostgresDeliveryRepository(database.pool)
    source = PostgresSourceRepository(delivery)

    class SharingViolation(_MovingSource):
        def cleanup_obsolete(self, job_id: UUID, tokens: tuple[int, ...]) -> None:
            raise PermissionError("synthetic sharing violation")

    handler = SourceAcquisitionHandler(source, SharingViolation(SourceStore(tmp_path / "store")))
    event = await event_for(database)
    lease = await delivery.claim(event, "indexer", uuid4())
    assert isinstance(lease, Lease)
    outcome = await handler.handle(lease)
    assert isinstance(outcome, TransientFailure)
    assert outcome.code == "SOURCE_IO_FAILED"


@pytest.mark.asyncio
async def test_janitor_dependency_failure_recovers_and_cancels(
    database: DatabaseHarness, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class RecoveringRepository(PostgresSourceRepository):
        calls = 0
        recovered = asyncio.Event()

        async def cleanup_candidates(self) -> tuple[tuple[UUID, int], ...]:
            self.calls += 1
            if self.calls == 1:
                raise OperationalError("synthetic-sensitive-diagnostic")
            result = await super().cleanup_candidates()
            self.recovered.set()
            return result

    repository = RecoveringRepository(PostgresDeliveryRepository(database.pool))
    handler = SourceAcquisitionHandler(repository, _MovingSource(SourceStore(tmp_path / "store")))
    stopping = asyncio.Event()
    task = asyncio.create_task(handler.run_cleanup(stopping, interval_seconds=0.01))
    try:
        await asyncio.wait_for(repository.recovered.wait(), timeout=2)
        assert not task.done()
        assert repository.calls >= 2
        assert "synthetic-sensitive-diagnostic" not in caplog.text
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
