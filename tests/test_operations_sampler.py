"""A sampler outage is visible and does not terminate the API role."""

from __future__ import annotations

import math

import pytest

from reposcope.application.operations import OperationalSampler
from reposcope.metrics import SNAPSHOT_UP, WORK_BACKLOG


class UnavailableRepository:
    def __init__(self) -> None:
        self.available = False

    async def snapshot(self) -> tuple[int, int, int]:
        if not self.available:
            raise ConnectionError("postgresql://user:secret@host/database")
        return (2, 1, 3)


@pytest.mark.asyncio
async def test_sampler_marks_failure_without_exposing_connection_text() -> None:
    repository = UnavailableRepository()
    sampler = OperationalSampler(repository)
    await sampler.sample_once()
    assert SNAPSHOT_UP._value.get() == 0
    assert math.isnan(WORK_BACKLOG.labels(kind="jobs")._value.get())
    repository.available = True
    await sampler.sample_once()
    assert SNAPSHOT_UP._value.get() == 1
    assert WORK_BACKLOG.labels(kind="jobs")._value.get() == 2
