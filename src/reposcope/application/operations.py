"""Best-effort private backlog sampling with explicit stale-data signaling."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Protocol

from reposcope.application.delivery import pause
from reposcope.metrics import SNAPSHOT_UP, WORK_BACKLOG

LOGGER = logging.getLogger("reposcope.operations")


class OperationalRepository(Protocol):
    async def snapshot(self) -> tuple[int, int, int]: ...


class OperationalSampler:
    def __init__(self, repository: OperationalRepository) -> None:
        self.repository = repository

    async def sample_once(self) -> None:
        """A failed sample never leaves old backlog values looking current."""
        try:
            jobs, runs, unpublished = await self.repository.snapshot()
            if min(jobs, runs, unpublished) < 0:
                raise ValueError("Negative backlog")
        except asyncio.CancelledError:
            raise
        except Exception:
            for kind in ("jobs", "runs", "unpublished"):
                WORK_BACKLOG.labels(kind=kind).set(math.nan)
            SNAPSHOT_UP.set(0)
            LOGGER.warning(
                "work_snapshot_unavailable", extra={"error_code": "DEPENDENCY_UNAVAILABLE"}
            )
            return
        for kind, count in (("jobs", jobs), ("runs", runs), ("unpublished", unpublished)):
            WORK_BACKLOG.labels(kind=kind).set(count)
        SNAPSHOT_UP.set(1)

    async def run(self, stopping: asyncio.Event) -> None:
        while not stopping.is_set():
            await self.sample_once()
            await pause(stopping, 15)
