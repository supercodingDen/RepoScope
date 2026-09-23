"""Opt-in T07 latency baseline over version-pinned public Python source."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from contracts.models import SearchRequest
from reposcope.adapters.embedding import MockEmbeddingProvider
from reposcope.adapters.postgres_index import PostgresIndexRepository
from reposcope.adapters.postgres_retrieval import PostgresRetrievalRepository
from reposcope.application.index import IndexHandler
from reposcope.application.retrieval import RetrievalService
from reposcope.domain.delivery import Lease, Staged
from reposcope.domain.indexing import chunk_file
from reposcope.domain.source import SourceRejected, classify_content, classify_path
from tests.integration.test_index import staged_files
from tests.integration.test_work_persistence import DatabaseHarness, database

pytestmark = pytest.mark.integration
__all__ = ["database"]


def _public_corpus(root: Path) -> tuple[dict[str, bytes], str, int]:
    files: dict[str, bytes] = {}
    fingerprint = hashlib.sha256()
    chunks = 0
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        try:
            if classify_path(relative) is not None or path.stat().st_size > 1024 * 1024:
                continue
        except SourceRejected:
            continue
        content = path.read_bytes()
        if classify_content(content) is not None:
            continue
        try:
            parsed = chunk_file(f"cpython/{relative}", content)
        except (UnicodeDecodeError, ValueError):
            continue
        if not parsed.chunks:
            continue
        files[f"cpython/{relative}"] = content
        fingerprint.update(relative.encode("utf-8"))
        fingerprint.update(hashlib.sha256(content).digest())
        chunks += len(parsed.chunks)
        if chunks >= 1000:
            break
    if chunks < 1000:
        raise RuntimeError("Public corpus contains fewer than 1000 eligible chunks")
    return files, fingerprint.hexdigest(), chunks


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return round(ordered[(95 * len(ordered) + 99) // 100 - 1], 3)


@pytest.mark.asyncio
async def test_public_source_retrieval_latency_baseline(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    configured = os.environ.get("T07_BENCH_SOURCE_ROOT")
    if configured is None:
        pytest.skip("Set T07_BENCH_SOURCE_ROOT to a verified public CPython 3.12.14 Lib tree")
    root = Path(configured)
    if not root.is_dir():
        raise RuntimeError("Configured public benchmark root is missing")
    files, fingerprint, chunks = _public_corpus(root)
    delivery, store, event = await staged_files(database, tmp_path, files, "retrieval-scale")
    lease = await delivery.claim(event, "source", uuid4())
    assert isinstance(lease, Lease)
    assert isinstance(
        await IndexHandler(
            PostgresIndexRepository(delivery), store, MockEmbeddingProvider()
        ).handle(lease),
        Staged,
    )
    repository = PostgresRetrievalRepository(database.pool)
    service = RetrievalService(repository, MockEmbeddingProvider())
    scope = await repository.active_scope(database.principal, event.payload.repository_id)
    assert scope is not None and scope.chunk_count == chunks
    vector = (1.0,) + (0.0,) * 383
    request = SearchRequest(repository_id=scope.repository_id, query="class")
    measurements: dict[str, list[float]] = {"exact_db": [], "hnsw_db": [], "text_search": []}
    for _ in range(5):
        await repository.candidates(scope, vector, "class", None, None, exact=True)
        await repository.candidates(scope, vector, "class", None, None)
        await service.search(request, database.principal)
    for _ in range(3):
        for _ in range(20):
            for name, exact in (("exact_db", True), ("hnsw_db", False)):
                started = time.perf_counter()
                await repository.candidates(scope, vector, "class", None, None, exact=exact)
                measurements[name].append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            await service.search(request, database.principal)
            measurements["text_search"].append((time.perf_counter() - started) * 1000)
    print(
        "T07_RETRIEVAL_BASELINE="
        + json.dumps(
            {
                "source_fingerprint": fingerprint,
                "files": len(files),
                "chunks": chunks,
                "trials": 3,
                "queries_per_trial": 20,
                "p95_ms": {name: _p95(values) for name, values in measurements.items()},
            },
            sort_keys=True,
        ),
        flush=True,
    )
