"""Real PostgreSQL index publication and independent source attempt acceptance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from contracts.models import IngestRequested, SourceAcquired
from reposcope.adapters.embedding import MockEmbeddingProvider
from reposcope.adapters.embedding_budget import PostgresEmbeddingBudget
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.adapters.postgres_index import PostgresIndexRepository
from reposcope.adapters.postgres_source import PostgresSourceRepository
from reposcope.adapters.source_storage import SnapshotBuilder, SourceStore
from reposcope.application.index import IndexHandler
from reposcope.domain.delivery import Lease, LeaseLost, Staged
from reposcope.domain.indexing import EmbeddingBatch, EmbeddingResponse, chunk_file
from reposcope.domain.source import SourceLimits
from reposcope.ports.embedding import EmbeddingBudgetExceeded, EmbeddingPriceStale
from tests.integration.test_work_persistence import DatabaseHarness, database, ingest

pytestmark = pytest.mark.integration
__all__ = ["database"]


async def staged_files(
    database: DatabaseHarness, tmp_path: Path, files: dict[str, bytes], key: str = "ingest"
) -> tuple[PostgresDeliveryRepository, SourceStore, SourceAcquired]:
    accepted = await ingest(database, key=key)
    delivery = PostgresDeliveryRepository(database.pool)
    source = PostgresSourceRepository(delivery)
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE job_id=%s "
        "AND event_type='repo.ingest.requested'",
        (accepted.job_id,),
    )
    request_row = await cursor.fetchone()
    assert request_row is not None
    ingest_event = IngestRequested.model_validate_json(request_row[0])
    source_lease = await delivery.claim(ingest_event, "indexer", uuid4())
    assert isinstance(source_lease, Lease)
    request = await source.prepare(source_lease)
    commit = await source.pin(source_lease, "a" * 40)
    store = SourceStore(tmp_path / "store")
    attempt = store.attempt(ingest_event.aggregate_id, source_lease.token)
    builder = SnapshotBuilder(attempt, SourceLimits())
    for path, content in files.items():
        assert builder.path(path)
        builder.add(path, content)
    snapshot = store.finalize(
        attempt, ingest_event.aggregate_id, builder.manifest(request.url, commit)
    )
    store.cleanup(attempt)
    await source.stage(source_lease, snapshot)
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events "
        "WHERE event_type='repo.source.acquired' AND job_id=%s",
        (accepted.job_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    event = SourceAcquired.model_validate_json(row[0])
    assert await delivery.authorized(event)
    return delivery, store, event


@pytest.mark.asyncio
async def test_duplicate_source_bytes_retain_distinct_citations_and_publish_atomically(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, event = await staged_files(
        database,
        tmp_path,
        {
            "alpha.py": b"def answer():\n    return 42\n",
            "beta.py": b"def answer():\n    return 42\n",
        },
    )
    lease = await delivery.claim(event, "source", uuid4())
    assert isinstance(lease, Lease) and lease.attempt == 1
    index = PostgresIndexRepository(delivery)
    handler = IndexHandler(index, store, MockEmbeddingProvider())
    assert isinstance(await handler.handle(lease), Staged)
    assert await delivery.completed("source", event.event_id)
    cursor = await database.owner.execute(
        "SELECT status,active_generation_id::text FROM reposcope.repositories "
        "JOIN reposcope.index_generations USING(repository_id)"
    )
    ready = await cursor.fetchone()
    assert ready == ("ready", str(event.payload.generation_id))
    cursor = await database.owner.execute(
        "SELECT path,ordinal::text,start_line::text,end_line::text "
        "FROM reposcope.index_chunks ORDER BY path,ordinal"
    )
    assert await cursor.fetchall() == [("alpha.py", "0", "1", "2"), ("beta.py", "0", "1", "2")]
    cursor = await database.owner.execute(
        "SELECT status,progress_percent::text,index_attempts::text FROM reposcope.jobs"
    )
    assert await cursor.fetchone() == ("succeeded", "100", "1")
    cursor = await database.owner.execute(
        "SELECT chunk_count::text FROM reposcope.index_generations WHERE generation_id=%s",
        (event.payload.generation_id,),
    )
    assert await cursor.fetchone() == ("2",)
    with pytest.raises(LeaseLost):
        await handler.repository.prepare(lease, handler.pipeline_version)


@pytest.mark.asyncio
async def test_paid_embedding_reservation_is_durable_and_bounded(
    database: DatabaseHarness,
) -> None:
    budget = PostgresEmbeddingBudget(
        database.pool, Decimal("0.000001"), Decimal("0.02"), datetime.now(UTC).date()
    )
    first = await budget.reserve(10)
    second = await budget.reserve(10)
    with pytest.raises(EmbeddingBudgetExceeded):
        await budget.reserve(10)
    await budget.settle(first, 9)
    await budget.uncertain(second)
    with pytest.raises(EmbeddingBudgetExceeded):
        await budget.reserve(10)
    cursor = await database.owner.execute(
        "SELECT state,actual_tokens::text FROM reposcope.embedding_reservations ORDER BY state"
    )
    assert await cursor.fetchall() == [("settled", "9"), ("uncertain", None)]
    stale = PostgresEmbeddingBudget(
        database.pool,
        Decimal("1"),
        Decimal("0.02"),
        datetime.now(UTC).date() - timedelta(days=8),
    )
    with pytest.raises(EmbeddingPriceStale):
        await stale.reserve(10)


@pytest.mark.asyncio
async def test_fifth_source_attempt_still_allows_first_index_attempt(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, event = await staged_files(database, tmp_path, {"one.py": b"x = 1\n"})
    await database.owner.execute("UPDATE reposcope.jobs SET attempts=5")
    lease = await delivery.claim(event, "source", uuid4())
    assert isinstance(lease, Lease) and lease.attempt == 1
    handler = IndexHandler(PostgresIndexRepository(delivery), store, MockEmbeddingProvider())
    assert isinstance(await handler.handle(lease), Staged)


@pytest.mark.asyncio
async def test_partial_checkpoint_is_invisible_and_replayed_once(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, event = await staged_files(
        database, tmp_path, {"one.py": b"x = 1\n", "two.py": b"y = 2\n"}
    )
    repository = PostgresIndexRepository(delivery)
    handler = IndexHandler(repository, store, MockEmbeddingProvider())
    first = await delivery.claim(event, "source", uuid4())
    assert isinstance(first, Lease)
    preparation = await repository.prepare(first, handler.pipeline_version)
    source_file = preparation.snapshot.manifest.files[0]
    chunked = chunk_file(source_file.path, store.read_blob(preparation.snapshot, source_file))
    response = await handler._embed_file(chunked)
    await repository.stage_file(
        first, chunked, source_file.sha256, source_file.size, response, handler.pipeline_version
    )
    cursor = await database.owner.execute(
        "SELECT g.status,r.active_generation_id::text FROM reposcope.index_generations g "
        "JOIN reposcope.repositories r USING(repository_id)"
    )
    row = await cursor.fetchone()
    assert row is not None and row[0] == "staged" and row[1] is None
    await delivery.release(first, 0)
    retry = await delivery.claim(event, "source", uuid4())
    assert isinstance(retry, Lease)
    with pytest.raises(LeaseLost):
        await repository.stage_file(
            first,
            chunked,
            source_file.sha256,
            source_file.size,
            response,
            handler.pipeline_version,
        )
    assert isinstance(await handler.handle(retry), Staged)
    cursor = await database.owner.execute("SELECT count(*)::text FROM reposcope.index_chunks")
    assert await cursor.fetchone() == ("2",)


@pytest.mark.asyncio
async def test_superseded_generation_never_replaces_active_pointer(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, event = await staged_files(database, tmp_path, {"one.py": b"x = 1\n"})
    newer = await ingest(database, key="newer-generation")
    assert newer.job_id != event.aggregate_id
    lease = await delivery.claim(event, "source", uuid4())
    assert isinstance(lease, Lease)
    handler = IndexHandler(PostgresIndexRepository(delivery), store, MockEmbeddingProvider())
    assert isinstance(await handler.handle(lease), Staged)
    cursor = await database.owner.execute(
        "SELECT status,chunk_count::text FROM reposcope.index_generations WHERE generation_id=%s",
        (event.payload.generation_id,),
    )
    assert await cursor.fetchone() == ("superseded", "1")
    cursor = await database.owner.execute(
        "SELECT active_generation_id::text FROM reposcope.repositories"
    )
    row = await cursor.fetchone()
    assert row is not None and row[0] is None


@pytest.mark.asyncio
async def test_empty_eligible_generation_is_ready(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, event = await staged_files(database, tmp_path, {})
    lease = await delivery.claim(event, "source", uuid4())
    assert isinstance(lease, Lease)
    handler = IndexHandler(PostgresIndexRepository(delivery), store, MockEmbeddingProvider())
    assert isinstance(await handler.handle(lease), Staged)
    cursor = await database.owner.execute(
        "SELECT status,chunk_count::text FROM reposcope.index_generations WHERE generation_id=%s",
        (event.payload.generation_id,),
    )
    assert await cursor.fetchone() == ("ready", "0")


@pytest.mark.asyncio
async def test_same_source_rerun_uses_cached_vectors_without_collapsing_locations(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    files = {"one.py": b"x = 1\n", "two.py": b"x = 1\n"}
    delivery, store, first_event = await staged_files(database, tmp_path, files)
    first_lease = await delivery.claim(first_event, "source", uuid4())
    assert isinstance(first_lease, Lease)
    first_handler = IndexHandler(PostgresIndexRepository(delivery), store, MockEmbeddingProvider())
    assert isinstance(await first_handler.handle(first_lease), Staged)
    delivery, store, second_event = await staged_files(
        database, tmp_path, files, key="same-source-rerun"
    )

    class CountingMock(MockEmbeddingProvider):
        calls = 0

        async def embed(self, batch: EmbeddingBatch) -> EmbeddingResponse:
            self.calls += 1
            return await super().embed(batch)

    provider = CountingMock()
    second_lease = await delivery.claim(second_event, "source", uuid4())
    assert isinstance(second_lease, Lease)
    assert isinstance(
        await IndexHandler(PostgresIndexRepository(delivery), store, provider).handle(second_lease),
        Staged,
    )
    assert provider.calls == 0
    cursor = await database.owner.execute(
        "SELECT count(*)::text FROM reposcope.index_chunks WHERE generation_id=%s",
        (second_event.payload.generation_id,),
    )
    assert await cursor.fetchone() == ("2",)


@pytest.mark.asyncio
async def test_forged_source_event_is_rejected_against_manifest(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, _, event = await staged_files(database, tmp_path, {"one.py": b"x = 1\n"})
    raw = event.model_dump()
    raw["payload"]["manifest_digest"] = "f" * 64
    forged = SourceAcquired.model_validate(raw)
    assert not await delivery.authorized(forged)
    assert await delivery.authorized(event)


@pytest.mark.asyncio
async def test_index_attempt_exhaustion_reconciles_staged_job(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, _, event = await staged_files(database, tmp_path, {"one.py": b"x = 1\n"})
    await database.owner.execute("UPDATE reposcope.jobs SET index_attempts=5")
    assert await delivery.reconcile() == 1
    cursor = await database.owner.execute(
        "SELECT j.status,j.failure_code,g.status FROM reposcope.jobs j "
        "JOIN reposcope.index_generations g ON g.generation_id=j.generation_id"
    )
    assert await cursor.fetchone() == ("failed", "ATTEMPTS_EXHAUSTED", "failed")
    assert await delivery.completed("source", event.event_id)
