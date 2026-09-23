"""Bounded source-to-index orchestration over verified immutable snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial

from contracts.models import SourceAcquired
from reposcope.domain.delivery import Lease, Outcome, PermanentFailure, Staged
from reposcope.domain.indexing import (
    CHUNK_POLICY_VERSION,
    PARSER_VERSION,
    TOKENIZER_VERSION,
    ChunkedFile,
    EmbeddingBatch,
    EmbeddingResponse,
    IndexChunk,
    chunk_file,
    embedding_input,
    validate_embedding_response,
)
from reposcope.domain.source import SourceRejected
from reposcope.ports.embedding import (
    EmbeddingBudgetExceeded,
    EmbeddingPriceStale,
    EmbeddingProvider,
)
from reposcope.ports.index import IndexRepository, SourceSnapshotReader


class _IndexMonitor:
    def __init__(self, stop: threading.Event, deadline: datetime) -> None:
        self.stop = stop
        self.deadline = deadline

    def check_time(self) -> None:
        if self.stop.is_set():
            raise SourceRejected("INDEX_CANCELLED")
        if datetime.now(UTC) >= self.deadline:
            raise SourceRejected("INDEX_DEADLINE")

    def check(self) -> None:
        self.check_time()


async def _run_thread[T](operation: Callable[[], T], stop: threading.Event) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        stop.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                pass
        if not task.cancelled():
            task.exception()
        raise


def _bounded_groups(chunks: tuple[IndexChunk, ...]) -> Iterator[tuple[IndexChunk, ...]]:
    group: list[IndexChunk] = []
    tokens = 0
    for chunk in chunks:
        if group and (len(group) == 32 or tokens + chunk.token_count > 20_000):
            yield tuple(group)
            group = []
            tokens = 0
        group.append(chunk)
        tokens += chunk.token_count
    if group:
        yield tuple(group)


class IndexHandler:
    configured = True

    def __init__(
        self, repository: IndexRepository, store: SourceSnapshotReader, provider: EmbeddingProvider
    ) -> None:
        self.repository = repository
        self.store = store
        self.provider = provider
        self.slots = asyncio.Semaphore(2)

    @property
    def pipeline_version(self) -> str:
        return "/".join(
            (PARSER_VERSION, TOKENIZER_VERSION, CHUNK_POLICY_VERSION, self.provider.space.version)
        )

    async def handle(self, lease: Lease) -> Outcome:
        if not isinstance(lease.event, SourceAcquired):
            return PermanentFailure("INDEX_EVENT_INVALID")
        async with self.slots:
            stop = threading.Event()
            monitor = _IndexMonitor(stop, lease.deadline)
            try:
                preparation = await self.repository.prepare(lease, self.pipeline_version)
                await _run_thread(lambda: self.store.validate(preparation.snapshot, monitor), stop)
                for file in preparation.snapshot.manifest.files:
                    if file.path in preparation.completed_paths:
                        continue
                    content = await _run_thread(
                        partial(self.store.read_blob, preparation.snapshot, file, monitor), stop
                    )
                    chunked = await _run_thread(
                        partial(chunk_file, file.path, content, monitor.check_time), stop
                    )
                    response = await self._embed_file(chunked, lease)
                    await self.repository.stage_file(
                        lease, chunked, file.sha256, file.size, response, self.pipeline_version
                    )
                await self.repository.publish(
                    lease, len(preparation.snapshot.manifest.files), self.provider.space.version
                )
                return Staged()
            except SourceRejected as error:
                if error.code == "INDEX_DEADLINE":
                    return PermanentFailure("INDEX_DEADLINE")
                if error.code == "INDEX_CANCELLED":
                    raise asyncio.CancelledError() from error
                return PermanentFailure("SOURCE_SNAPSHOT_CORRUPT")
            except EmbeddingBudgetExceeded:
                return PermanentFailure("EMBEDDING_BUDGET_EXCEEDED")
            except EmbeddingPriceStale:
                return PermanentFailure("EMBEDDING_PRICE_STALE")
            except (UnicodeDecodeError, ValueError):
                return PermanentFailure("INDEX_CONTENT_INVALID")

    async def _embed_file(
        self, file: ChunkedFile, lease: Lease | None = None
    ) -> EmbeddingResponse | None:
        if not file.chunks:
            return None
        keys = tuple(
            hashlib.sha256(embedding_input(chunk).encode("utf-8")).hexdigest()
            for chunk in file.chunks
        )
        cached = (
            await self.repository.cached_embeddings(self.provider.space.version, keys)
            if lease is not None
            else {}
        )
        vectors: list[tuple[float, ...]] = []
        offset = 0
        for group in _bounded_groups(file.chunks):
            group_keys = keys[offset : offset + len(group)]
            offset += len(group)
            missing = [
                chunk for chunk, key in zip(group, group_keys, strict=True) if key not in cached
            ]
            new_vectors: tuple[tuple[float, ...], ...] = ()
            if missing:
                inputs = tuple(embedding_input(chunk) for chunk in missing)
                batch = EmbeddingBatch(inputs, tuple(chunk.token_count for chunk in missing))
                response = await self.provider.embed(batch)
                if response.space != self.provider.space:
                    raise ValueError("Embedding model identity changed")
                new_vectors = response.vectors
            delivered = iter(new_vectors)
            group_vectors = tuple(
                cached[key] if key in cached else next(delivered) for key in group_keys
            )
            full_batch = EmbeddingBatch(
                tuple(embedding_input(chunk) for chunk in group),
                tuple(chunk.token_count for chunk in group),
            )
            vectors.extend(
                validate_embedding_response(full_batch, self.provider.space, group_vectors).vectors
            )
        return EmbeddingResponse(self.provider.space, tuple(vectors))
