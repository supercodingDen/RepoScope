"""Source acquisition contracts independent of external SDKs."""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from reposcope.domain.delivery import Lease
from reposcope.domain.source import SourceLimits
from reposcope.domain.source_snapshot import SourceSnapshot


@dataclass(frozen=True, slots=True)
class SourceRequest:
    url: str
    generation_id: UUID
    commit_sha: str | None


class SourceRepository(Protocol):
    async def cleanup_candidates(self) -> tuple[tuple[UUID, int], ...]: ...
    async def cleaned(self, job_id: UUID, token: int) -> None: ...
    async def prepare(self, lease: Lease) -> SourceRequest: ...
    async def pin(self, lease: Lease, commit: str) -> str: ...
    async def stage(self, lease: Lease, snapshot: SourceSnapshot) -> None: ...
    async def obsolete_attempts(self, lease: Lease) -> tuple[int, ...]: ...


class SourceSession(Protocol):
    def resolve(self, reference: str) -> str: ...
    def acquire(self, commit: str) -> SourceSnapshot: ...


class SourceBackend(Protocol):
    def session(
        self, url: str, job_id: UUID, token: int, limits: SourceLimits, stop: threading.Event
    ) -> AbstractContextManager[SourceSession]: ...
    def cleanup_obsolete(self, job_id: UUID, tokens: tuple[int, ...]) -> None: ...
