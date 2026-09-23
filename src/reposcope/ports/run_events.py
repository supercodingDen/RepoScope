"""Typed durable timeline boundary for the public SSE workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from contracts.models import RunEvent


@dataclass(frozen=True, slots=True)
class EventBatch:
    events: tuple[RunEvent, ...]
    terminal: bool


class RunEventStore(Protocol):
    async def open(self, principal_id: UUID, run_id: UUID, after: int) -> UUID: ...

    async def batch(
        self, connection_id: UUID, principal_id: UUID, run_id: UUID, after: int
    ) -> EventBatch: ...

    async def release(self, connection_id: UUID) -> None: ...
