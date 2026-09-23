"""Embedding boundary used by indexing without importing provider SDKs."""

from __future__ import annotations

from typing import Protocol

from reposcope.domain.indexing import EmbeddingBatch, EmbeddingResponse, EmbeddingSpace


class EmbeddingBudgetExceeded(Exception):
    """The configured daily ceiling does not admit another provider request."""


class EmbeddingPriceStale(Exception):
    """The locally authorized unit price is no longer current."""


class EmbeddingProvider(Protocol):
    space: EmbeddingSpace

    async def embed(self, batch: EmbeddingBatch) -> EmbeddingResponse: ...
