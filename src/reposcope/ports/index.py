"""Index persistence and verified snapshot reading boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from reposcope.domain.delivery import Lease
from reposcope.domain.indexing import ChunkedFile, EmbeddingResponse
from reposcope.domain.source_snapshot import SourceFile, SourceSnapshot


@dataclass(frozen=True, slots=True)
class IndexPreparation:
    snapshot: SourceSnapshot
    completed_paths: frozenset[str]


class IndexRepository(Protocol):
    async def prepare(self, lease: Lease, pipeline_version: str) -> IndexPreparation: ...

    async def cached_embeddings(
        self, space_version: str, input_hashes: tuple[str, ...]
    ) -> dict[str, tuple[float, ...]]: ...

    async def stage_file(
        self,
        lease: Lease,
        file: ChunkedFile,
        content_sha256: str,
        byte_count: int,
        response: EmbeddingResponse | None,
        pipeline_version: str,
    ) -> None: ...

    async def publish(self, lease: Lease, expected_files: int, space_version: str) -> str: ...


class SourceMonitor(Protocol):
    def check_time(self) -> None: ...

    def check(self) -> None: ...


class SourceSnapshotReader(Protocol):
    def validate(self, snapshot: SourceSnapshot, monitor: SourceMonitor | None = None) -> None: ...

    def read_blob(
        self, snapshot: SourceSnapshot, file: SourceFile, monitor: SourceMonitor | None = None
    ) -> bytes: ...
