"""Bounded, provider-compatible search over a pinned ready generation."""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

import tiktoken

from contracts.models import SearchMatch, SearchRequest, SearchResponse
from reposcope.domain.errors import WorkError
from reposcope.domain.indexing import EmbeddingBatch, validate_embedding_response
from reposcope.domain.retrieval import chunk_uuid, fuse_candidates
from reposcope.ports.embedding import (
    EmbeddingBudgetExceeded,
    EmbeddingPriceStale,
    EmbeddingProvider,
)
from reposcope.ports.retrieval import RetrievalRepository


def _query_tokens(query: str) -> int:
    return len(tiktoken.get_encoding("cl100k_base").encode(query))


class RetrievalService:
    """One search workflow shared by API and future agent tools."""

    def __init__(self, repository: RetrievalRepository, provider: EmbeddingProvider) -> None:
        self.repository = repository
        self.provider = provider

    async def search(self, request: SearchRequest, principal_id: UUID) -> SearchResponse:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(10):
                scope = await self.repository.active_scope(principal_id, request.repository_id)
                if scope is None:
                    raise WorkError("INDEX_NOT_READY")
                if scope.embedding_space_version != self.provider.space.version:
                    raise WorkError("PROVIDER_UNAVAILABLE")
                if scope.chunk_count == 0:
                    return SearchResponse(
                        repository_id=scope.repository_id,
                        generation_id=scope.generation_id,
                        commit_sha=scope.commit_sha,
                        results=[],
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                tokens = await asyncio.to_thread(_query_tokens, request.query)
                if not 1 <= tokens <= 800:
                    raise WorkError("VALIDATION_ERROR")
                batch = EmbeddingBatch((request.query,), (tokens,))
                try:
                    response = await self.provider.embed(batch)
                    if response.space != self.provider.space:
                        raise ValueError("Embedding space mismatch")
                    verified = validate_embedding_response(
                        batch, self.provider.space, response.vectors
                    )
                except (EmbeddingBudgetExceeded, EmbeddingPriceStale, asyncio.CancelledError):
                    raise
                except Exception:
                    raise WorkError("PROVIDER_UNAVAILABLE") from None
                vector, lexical = await self.repository.candidates(
                    scope,
                    verified.vectors[0],
                    request.query,
                    request.language,
                    request.path_prefix,
                )
                matches = [
                    SearchMatch(
                        chunk_id=chunk_uuid(scope.generation_id, item.path, item.ordinal),
                        repository_id=scope.repository_id,
                        generation_id=scope.generation_id,
                        commit_sha=scope.commit_sha,
                        path=item.path,
                        start_line=item.start_line,
                        end_line=item.end_line,
                        score=score,
                        content=item.content,
                    )
                    for item, score in fuse_candidates(vector, lexical, request.top_k)
                ]
                return SearchResponse(
                    repository_id=scope.repository_id,
                    generation_id=scope.generation_id,
                    commit_sha=scope.commit_sha,
                    results=matches,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
        except TimeoutError:
            raise WorkError("PROVIDER_TIMEOUT") from None
        except EmbeddingBudgetExceeded:
            raise WorkError("BUDGET_EXCEEDED") from None
        except EmbeddingPriceStale:
            raise WorkError("PROVIDER_UNAVAILABLE") from None
