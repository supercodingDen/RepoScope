"""T07 ranking and scoped search behavior."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from contracts.models import SearchRequest
from reposcope.adapters.postgres_retrieval import complete_vector_candidates
from reposcope.application.retrieval import RetrievalService
from reposcope.domain.errors import WorkError
from reposcope.domain.indexing import EmbeddingBatch, EmbeddingResponse, EmbeddingSpace
from reposcope.domain.retrieval import Candidate, RetrievalScope, chunk_uuid, fuse_candidates


def candidate(path: str, ordinal: int) -> Candidate:
    return Candidate(path, ordinal, 1, 3, "needle", "python")


def test_rrf_deduplicates_and_breaks_ties_by_path() -> None:
    vector = (candidate("b.py", 0), candidate("a.py", 0))
    lexical = (candidate("a.py", 0), candidate("b.py", 0))
    ranked = fuse_candidates(vector, lexical, 2)
    assert [(item.path, item.ordinal) for item, _ in ranked] == [("a.py", 0), ("b.py", 0)]
    assert ranked[0][1] == ranked[1][1]


def test_chunk_id_stable_and_location_specific() -> None:
    generation = uuid4()
    assert chunk_uuid(generation, "a.py", 0) == chunk_uuid(generation, "a.py", 0)
    assert chunk_uuid(generation, "a.py", 0) != chunk_uuid(generation, "b.py", 0)


class FakeRepository:
    def __init__(self, scope: RetrievalScope | None) -> None:
        self.scope = scope
        self.calls: list[tuple[UUID, str | None, str | None]] = []

    async def active_scope(self, principal_id: UUID, repository_id: UUID) -> RetrievalScope | None:
        return self.scope

    async def pinned_scope(
        self, principal_id: UUID, repository_id: UUID, generation_id: UUID, commit_sha: str
    ) -> RetrievalScope | None:
        if self.scope is not None and (
            self.scope.repository_id,
            self.scope.generation_id,
            self.scope.commit_sha,
        ) == (repository_id, generation_id, commit_sha):
            return self.scope
        return None

    async def candidates(
        self,
        scope: RetrievalScope,
        vector: tuple[float, ...],
        query: str,
        language: str | None,
        path_prefix: str | None,
        *,
        exact: bool = False,
    ) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]:
        self.calls.append((scope.generation_id, language, path_prefix))
        return ((candidate("a.py", 0),), (candidate("a.py", 0),))


class FakeProvider:
    space = EmbeddingSpace("mock", "deterministic-sha256", 384, "mock-sha256-384-l2-v1")

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, batch: EmbeddingBatch) -> EmbeddingResponse:
        self.calls += 1
        return EmbeddingResponse(self.space, ((1.0,) + (0.0,) * 383,))


@pytest.mark.asyncio
async def test_search_returns_pinned_citation_and_applies_filters() -> None:
    repository_id, generation_id, principal_id = uuid4(), uuid4(), uuid4()
    scope = RetrievalScope(repository_id, generation_id, "a" * 40, FakeProvider.space.version)
    repository = FakeRepository(scope)
    provider = FakeProvider()
    response = await RetrievalService(repository, provider).search(
        SearchRequest(
            repository_id=repository_id,
            query="needle",
            language="python",
            path_prefix="a",
        ),
        principal_id,
    )
    assert repository.calls == [(generation_id, "python", "a")]
    assert len(response.results) == 1
    assert response.results[0].chunk_id == chunk_uuid(generation_id, "a.py", 0)
    assert response.results[0].commit_sha == "a" * 40


@pytest.mark.asyncio
async def test_missing_scope_and_mismatched_space_fail_before_provider_call() -> None:
    provider = FakeProvider()
    request = SearchRequest(repository_id=uuid4(), query="needle")
    with pytest.raises(WorkError) as missing:
        await RetrievalService(FakeRepository(None), provider).search(request, uuid4())
    assert missing.value.code == "INDEX_NOT_READY"
    scope = RetrievalScope(request.repository_id, uuid4(), "a" * 40, "different-space")
    with pytest.raises(WorkError) as mismatch:
        await RetrievalService(FakeRepository(scope), provider).search(request, uuid4())
    assert mismatch.value.code == "PROVIDER_UNAVAILABLE"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_query_over_token_limit_rejected_before_embedding() -> None:
    provider = FakeProvider()
    scope = RetrievalScope(uuid4(), uuid4(), "a" * 40, provider.space.version)
    request = SearchRequest(repository_id=scope.repository_id, query="x " * 900)
    with pytest.raises(WorkError) as rejected:
        await RetrievalService(FakeRepository(scope), provider).search(request, uuid4())
    assert rejected.value.code == "VALIDATION_ERROR"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_empty_ready_generation_does_not_call_provider() -> None:
    provider = FakeProvider()
    scope = RetrievalScope(uuid4(), uuid4(), "a" * 40, provider.space.version, 0)
    result = await RetrievalService(FakeRepository(scope), provider).search(
        SearchRequest(repository_id=scope.repository_id, query="needle"), uuid4()
    )
    assert result.results == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_provider_failure_is_safe_service_error() -> None:
    class FailingProvider(FakeProvider):
        async def embed(self, batch: EmbeddingBatch) -> EmbeddingResponse:
            raise RuntimeError("secret provider detail")

    provider = FailingProvider()
    scope = RetrievalScope(uuid4(), uuid4(), "a" * 40, provider.space.version)
    with pytest.raises(WorkError) as failed:
        await RetrievalService(FakeRepository(scope), provider).search(
            SearchRequest(repository_id=scope.repository_id, query="needle"), uuid4()
        )
    assert failed.value.code == "PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_pinned_search_preserves_old_complete_generation_scope() -> None:
    provider = FakeProvider()
    old = RetrievalScope(uuid4(), uuid4(), "a" * 40, provider.space.version)
    repository = FakeRepository(old)
    service = RetrievalService(repository, provider)
    result = await service.search_pinned(
        SearchRequest(repository_id=old.repository_id, query="needle"),
        uuid4(),
        old.generation_id,
        old.commit_sha,
    )
    assert result.generation_id == old.generation_id
    assert repository.calls[0][0] == old.generation_id
    with pytest.raises(WorkError) as forged:
        await service.search_pinned(
            SearchRequest(repository_id=old.repository_id, query="needle"),
            uuid4(),
            uuid4(),
            old.commit_sha,
        )
    assert forged.value.code == "INDEX_NOT_READY"


@pytest.mark.asyncio
async def test_underfilled_ann_candidates_are_replaced_by_exact_scoped_top_50() -> None:
    calls = 0

    async def exact() -> tuple[Candidate, ...]:
        nonlocal calls
        calls += 1
        return (candidate("allowed.py", 0), candidate("allowed.py", 1))

    result = await complete_vector_candidates((candidate("allowed.py", 0),), exact)
    assert [(item.path, item.ordinal) for item in result] == [
        ("allowed.py", 0),
        ("allowed.py", 1),
    ]
    assert calls == 1
