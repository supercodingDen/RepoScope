"""Cancellation must retain the indexer slot until its file thread stops."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from contracts.models import SourceAcquired, SourceAcquiredPayload
from reposcope.adapters.embedding import MockEmbeddingProvider
from reposcope.application.index import IndexHandler
from reposcope.domain.delivery import Lease
from reposcope.domain.source_snapshot import SourceManifest, SourceSnapshot
from reposcope.ports.index import IndexPreparation, IndexRepository, SourceSnapshotReader


@pytest.mark.asyncio
async def test_cancel_waits_for_snapshot_thread_before_releasing_slot() -> None:
    started = threading.Event()
    release = threading.Event()
    manifest = SourceManifest("https://github.com/example/repo", "a" * 40, (), {}, 0, 0, ())
    snapshot = SourceSnapshot(manifest, "snapshots/fixture")

    class Repository:
        async def prepare(self, lease: Lease, pipeline_version: str) -> IndexPreparation:
            return IndexPreparation(snapshot, frozenset())

    class Store:
        def validate(self, value: SourceSnapshot, monitor: object | None = None) -> None:
            started.set()
            release.wait(timeout=2)

    job = uuid4()
    event = SourceAcquired(
        event_id=uuid4(),
        aggregate_id=job,
        occurred_at=datetime.now(UTC),
        trace_id=uuid4(),
        payload=SourceAcquiredPayload(
            job_id=job,
            repository_id=uuid4(),
            generation_id=uuid4(),
            principal_id=uuid4(),
            commit_sha="a" * 40,
            manifest_digest=manifest.digest,
        ),
    )
    lease = Lease(event, "source", uuid4(), 1, datetime.now(UTC) + timedelta(minutes=1), 1)
    handler = IndexHandler(
        cast(IndexRepository, Repository()),
        cast(SourceSnapshotReader, Store()),
        MockEmbeddingProvider(),
    )
    task = asyncio.create_task(handler.handle(lease))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
