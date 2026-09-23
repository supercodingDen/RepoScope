"""Private backlog metrics reflect committed PostgreSQL work and recover from outages."""

from __future__ import annotations

import pytest

from reposcope.adapters.postgres_operations import PostgresOperationalRepository
from reposcope.application.operations import OperationalSampler
from reposcope.metrics import SNAPSHOT_UP, WORK_BACKLOG
from tests.integration.test_work_persistence import DatabaseHarness, database, ingest

pytestmark = pytest.mark.integration
__all__ = ["database"]


@pytest.mark.asyncio
async def test_backlog_sampler_counts_committed_work(database: DatabaseHarness) -> None:
    accepted = await ingest(database)
    sampler = OperationalSampler(PostgresOperationalRepository(database.pool))
    await sampler.sample_once()
    assert SNAPSHOT_UP._value.get() == 1
    assert WORK_BACKLOG.labels(kind="jobs")._value.get() == 1
    assert WORK_BACKLOG.labels(kind="runs")._value.get() == 0
    assert WORK_BACKLOG.labels(kind="unpublished")._value.get() == 1
    await database.owner.execute(
        "UPDATE reposcope.jobs SET status='failed',failure_code='TEST_FAILURE' WHERE job_id=%s",
        (accepted.job_id,),
    )
    await sampler.sample_once()
    assert WORK_BACKLOG.labels(kind="jobs")._value.get() == 0
    assert WORK_BACKLOG.labels(kind="unpublished")._value.get() == 0
