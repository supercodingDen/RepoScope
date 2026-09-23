"""Bounded embedding contracts without paid-provider calls."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from reposcope.adapters.embedding import MockEmbeddingProvider, OpenAIEmbeddingProvider
from reposcope.adapters.embedding_budget import PostgresEmbeddingBudget
from reposcope.domain.indexing import EmbeddingBatch, validate_embedding_response


@pytest.mark.asyncio
async def test_mock_vectors_are_deterministic_normalized_and_labeled() -> None:
    provider = MockEmbeddingProvider()
    batch = EmbeddingBatch(("path:a.py\nprint(1)", "path:b.py\nprint(2)"), (7, 7))

    first = await provider.embed(batch)
    repeated = await provider.embed(batch)

    assert first == repeated
    assert first.space.provider == "mock"
    assert first.space.dimensions == 384
    assert len(first.vectors) == 2
    assert first.vectors[0] != first.vectors[1]
    assert all(len(vector) == 384 for vector in first.vectors)
    assert all(
        abs(math.sqrt(sum(value * value for value in vector)) - 1) < 1e-9
        for vector in first.vectors
    )


def test_batch_rejects_excess_chunks_or_tokens() -> None:
    with pytest.raises(ValueError, match="32"):
        EmbeddingBatch(tuple("x" for _ in range(33)), tuple(1 for _ in range(33)))
    with pytest.raises(ValueError, match="20,000"):
        EmbeddingBatch(tuple("x" for _ in range(26)), tuple(800 for _ in range(26)))


def test_invalid_dimension_or_non_finite_provider_values_fail_closed() -> None:
    provider = MockEmbeddingProvider()
    batch = EmbeddingBatch(("x",), (1,))

    with pytest.raises(ValueError, match="dimensions"):
        validate_embedding_response(batch, provider.space, ((1.0,),))
    with pytest.raises(ValueError, match="finite"):
        validate_embedding_response(batch, provider.space, ((math.nan,) * 384,))


class _FakeBudget:
    def __init__(self) -> None:
        self.reserved: list[int] = []
        self.settled: list[int] = []
        self.uncertain_count = 0

    async def reserve(self, requested_tokens: int) -> UUID:
        self.reserved.append(requested_tokens)
        return uuid4()

    async def settle(self, reservation_id: UUID, actual_tokens: int) -> None:
        self.settled.append(actual_tokens)

    async def uncertain(self, reservation_id: UUID) -> None:
        self.uncertain_count += 1


@dataclass(frozen=True)
class _FakeItem:
    index: int
    embedding: list[float]


@dataclass(frozen=True)
class _FakeUsage:
    total_tokens: int


@dataclass(frozen=True)
class _FakeResult:
    model: str
    data: list[_FakeItem]
    usage: _FakeUsage


class _FakeEmbeddings:
    def __init__(
        self, result: _FakeResult | None = None, wait: asyncio.Event | None = None
    ) -> None:
        self.result = result
        self.wait = wait
        self.calls: list[tuple[str, int, list[str]]] = []

    async def create(self, *, model: str, dimensions: int, input: list[str]) -> _FakeResult:
        self.calls.append((model, dimensions, input))
        if self.wait is not None:
            await self.wait.wait()
        assert self.result is not None
        return self.result


class _FakeClient:
    def __init__(self, embeddings: _FakeEmbeddings) -> None:
        self.embeddings = embeddings

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_live_adapter_reserves_before_dispatch_and_settles_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _FakeBudget()
    vector = [0.0] * 384
    vector[0] = 1.0
    embeddings = _FakeEmbeddings(
        _FakeResult("text-embedding-3-small", [_FakeItem(0, vector)], _FakeUsage(6))
    )

    def client(*, api_key: str, max_retries: int, timeout: float) -> _FakeClient:
        assert api_key == "test-key"
        assert max_retries == 0
        assert timeout == 15.0
        assert budget.reserved == [6]
        return _FakeClient(embeddings)

    monkeypatch.setattr("reposcope.adapters.embedding.AsyncOpenAI", client)
    provider = OpenAIEmbeddingProvider("test-key", cast(PostgresEmbeddingBudget, budget))
    response = await provider.embed(EmbeddingBatch(("source",), (6,)))
    assert response.space.version == "openai-3-small-384-v1"
    assert embeddings.calls == [("text-embedding-3-small", 384, ["source"])]
    assert budget.settled == [6] and budget.uncertain_count == 0


@pytest.mark.asyncio
async def test_cancelled_live_dispatch_keeps_uncertain_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _FakeBudget()
    embeddings = _FakeEmbeddings(wait=asyncio.Event())

    def client(*, api_key: str, max_retries: int, timeout: float) -> _FakeClient:
        return _FakeClient(embeddings)

    monkeypatch.setattr("reposcope.adapters.embedding.AsyncOpenAI", client)
    provider = OpenAIEmbeddingProvider("test-key", cast(PostgresEmbeddingBudget, budget))
    task = asyncio.create_task(provider.embed(EmbeddingBatch(("source",), (6,))))
    while not embeddings.calls:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert budget.reserved == [6]
    assert budget.settled == []
    assert budget.uncertain_count == 1
