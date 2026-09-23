"""Typed storage boundary for scoped retrieval."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from contracts.models import SearchRequest, SearchResponse
from reposcope.domain.retrieval import Candidate, RetrievalScope


class SearchWorkflow(Protocol):
    async def search(self, request: SearchRequest, principal_id: UUID) -> SearchResponse: ...


class RetrievalRepository(Protocol):
    async def active_scope(
        self, principal_id: UUID, repository_id: UUID
    ) -> RetrievalScope | None: ...

    async def pinned_scope(
        self, principal_id: UUID, repository_id: UUID, generation_id: UUID, commit_sha: str
    ) -> RetrievalScope | None: ...

    async def candidates(
        self,
        scope: RetrievalScope,
        vector: tuple[float, ...],
        query: str,
        language: str | None,
        path_prefix: str | None,
        *,
        exact: bool = False,
    ) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]: ...
