"""Acquire outside transactions and commit a fenced source handoff."""

from __future__ import annotations

import asyncio
import logging
import threading

from contracts.models import IngestRequested
from reposcope.domain.delivery import Lease, Outcome, PermanentFailure, Staged, TransientFailure
from reposcope.domain.source import SourceLimits, SourceRejected
from reposcope.domain.source_snapshot import SourceSnapshot
from reposcope.ports.source import SourceBackend, SourceRepository, SourceRequest

LOGGER = logging.getLogger("reposcope.source")


class SourceAcquisitionHandler:
    configured = True

    def __init__(
        self,
        repository: SourceRepository,
        backend: SourceBackend,
        limits: SourceLimits | None = None,
    ) -> None:
        self.repository = repository
        self.backend = backend
        self.limits = limits or SourceLimits()
        self.slots = asyncio.Semaphore(2)

    async def handle(self, lease: Lease) -> Outcome:
        if not isinstance(lease.event, IngestRequested):
            return PermanentFailure("SOURCE_EVENT_INVALID")
        async with self.slots:
            request = await self.repository.prepare(lease)
            obsolete = await self.repository.obsolete_attempts(lease)
            stop = threading.Event()
            loop = asyncio.get_running_loop()

            def acquire() -> SourceSnapshot:
                self.backend.cleanup_obsolete(lease.event.aggregate_id, obsolete)
                return self._acquire(request, lease, stop, loop)

            task = asyncio.create_task(asyncio.to_thread(acquire))
            try:
                snapshot = await asyncio.shield(task)
                await self.repository.stage(lease, snapshot)
                return Staged()
            except asyncio.CancelledError:
                stop.set()
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except (asyncio.CancelledError, SourceRejected, OSError):
                        pass
                if not task.cancelled():
                    task.exception()
                raise
            except SourceRejected as error:
                if error.code in {
                    "SOURCE_NETWORK_FAILED",
                    "SOURCE_CONNECT_FAILED",
                    "SOURCE_DNS_FAILED",
                    "SOURCE_GIT_FAILED",
                }:
                    return TransientFailure(error.code)
                return PermanentFailure(error.code)
            except OSError:
                return TransientFailure("SOURCE_IO_FAILED")

    def _acquire(
        self,
        request: SourceRequest,
        lease: Lease,
        stop: threading.Event,
        loop: asyncio.AbstractEventLoop,
    ) -> SourceSnapshot:
        assert isinstance(lease.event, IngestRequested)
        with self.backend.session(
            request.url, lease.event.aggregate_id, lease.token, self.limits, stop
        ) as session:
            commit = request.commit_sha
            if commit is None:
                resolved = session.resolve(lease.event.payload.requested_ref)
                future = asyncio.run_coroutine_threadsafe(
                    self.repository.pin(lease, resolved), loop
                )
                try:
                    commit = future.result(timeout=12)
                finally:
                    if not future.done():
                        future.cancel()
            if stop.is_set():
                raise SourceRejected("SOURCE_CANCELLED")
            return session.acquire(commit)

    async def cleanup(self) -> None:
        async with self.slots:
            for job_id, token in await self.repository.cleanup_candidates():
                try:
                    await asyncio.to_thread(self.backend.cleanup_obsolete, job_id, (token,))
                except OSError:
                    continue
                await self.repository.cleaned(job_id, token)

    async def run_cleanup(self, stopping: asyncio.Event, *, interval_seconds: float = 30.0) -> None:
        if not 0 < interval_seconds <= 30:
            raise ValueError("Cleanup interval must be positive and bounded")
        while not stopping.is_set():
            try:
                await self.cleanup()
            except Exception:
                # This periodic boundary survives dependency outages; cancellation propagates.
                LOGGER.warning(
                    "source_cleanup_retry", extra={"error_code": "SOURCE_CLEANUP_UNAVAILABLE"}
                )
            try:
                await asyncio.wait_for(stopping.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
