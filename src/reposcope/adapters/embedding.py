"""Embedding implementations isolated from indexing orchestration."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence

from openai import AsyncOpenAI

from reposcope.adapters.embedding_budget import PostgresEmbeddingBudget
from reposcope.domain.indexing import (
    EmbeddingBatch,
    EmbeddingResponse,
    EmbeddingSpace,
    validate_embedding_response,
)


def _mock_vector(content: str) -> tuple[float, ...]:
    seed = content.encode("utf-8")
    values = tuple(
        (byte - 127.5) / 127.5
        for block in range(12)
        for byte in hashlib.sha256(block.to_bytes(2, "big") + seed).digest()
    )
    return values


def _mock_vectors(inputs: Sequence[str]) -> tuple[tuple[float, ...], ...]:
    return tuple(_mock_vector(value) for value in inputs)


class MockEmbeddingProvider:
    space = EmbeddingSpace("mock", "deterministic-sha256", 384, "mock-sha256-384-l2-v1")

    def __init__(self) -> None:
        self.slots = asyncio.Semaphore(2)

    async def embed(self, batch: EmbeddingBatch) -> EmbeddingResponse:
        """Return deterministic test vectors without provider calls."""
        async with self.slots:
            vectors = await asyncio.to_thread(_mock_vectors, batch.inputs)
            return validate_embedding_response(batch, self.space, vectors)


class OpenAIEmbeddingProvider:
    """Explicitly budgeted live adapter; never used by default."""

    space = EmbeddingSpace("openai", "text-embedding-3-small", 384, "openai-3-small-384-v1")

    def __init__(self, api_key: str, budget: PostgresEmbeddingBudget) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self.api_key = api_key
        self.budget = budget
        self.slots = asyncio.Semaphore(2)

    async def embed(self, batch: EmbeddingBatch) -> EmbeddingResponse:
        async with self.slots:
            reservation = await self.budget.reserve(sum(batch.token_counts))
            try:
                async with AsyncOpenAI(api_key=self.api_key, max_retries=0, timeout=15.0) as client:
                    result = await client.embeddings.create(
                        model=self.space.model,
                        dimensions=self.space.dimensions,
                        input=list(batch.inputs),
                    )
                if result.model != self.space.model:
                    raise ValueError("Embedding model identity mismatch")
                ordered = sorted(result.data, key=lambda item: item.index)
                if [item.index for item in ordered] != list(range(len(batch.inputs))):
                    raise ValueError("Embedding result indices mismatch")
                response = validate_embedding_response(
                    batch,
                    self.space,
                    tuple(tuple(float(value) for value in item.embedding) for item in ordered),
                )
                await self.budget.settle(reservation, result.usage.total_tokens)
                return response
            except BaseException:
                # A failed or cancelled request may still have reached the provider.
                await asyncio.shield(self.budget.uncertain(reservation))
                raise
