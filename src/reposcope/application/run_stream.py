"""Authenticated, bounded SSE replay over the durable run timeline."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator
from uuid import UUID

from contracts.models import RunEvent
from reposcope.domain.errors import WorkError
from reposcope.ports.run_events import RunEventStore


def parse_event_cursor(value: str | None, run_id: UUID) -> int:
    if value is None:
        return 0
    if len(value) > 64 or re.fullmatch(r"[0-9a-fA-F-]{36}:[0-9]{1,20}", value) is None:
        raise WorkError("VALIDATION_ERROR")
    identity, number = value.split(":", 1)
    try:
        if UUID(identity) != run_id:
            raise WorkError("VALIDATION_ERROR")
    except ValueError:
        raise WorkError("VALIDATION_ERROR") from None
    return int(number)


def event_frame(event: RunEvent) -> str:
    return (
        f"id: {event.run_id}:{event.sequence}\n"
        f"event: {event.data.kind}\n"
        f"data: {event.model_dump_json()}\n\n"
    )


class RunStream:
    def __init__(self, store: RunEventStore, *, heartbeat_seconds: float = 15) -> None:
        self.store = store
        self.heartbeat_seconds = heartbeat_seconds

    async def open(self, principal_id: UUID, run_id: UUID, cursor: str | None) -> tuple[UUID, int]:
        after = parse_event_cursor(cursor, run_id)
        connection_id = await self.store.open(principal_id, run_id, after)
        return connection_id, after

    async def stream(
        self, connection_id: UUID, principal_id: UUID, run_id: UUID, after: int
    ) -> AsyncGenerator[str, None]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_heartbeat = started
        try:
            while loop.time() - started < 180:
                batch = await self.store.batch(connection_id, principal_id, run_id, after)
                for event in batch.events:
                    yield event_frame(event)
                    after = event.sequence
                if batch.terminal and len(batch.events) < 100:
                    return
                now = loop.time()
                if now - last_heartbeat >= self.heartbeat_seconds:
                    yield ": keep-alive\n\n"
                    last_heartbeat = now
                if not batch.events:
                    await asyncio.sleep(1)
        finally:
            await self.store.release(connection_id)
