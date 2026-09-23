"""Three snapshot-scoped, read-only tools for agent execution."""

from __future__ import annotations

import asyncio
from uuid import UUID

import tiktoken

from contracts.models import (
    FileResult,
    GetFileTool,
    RepositorySummary,
    SearchCodeTool,
    SearchMatch,
    SearchRequest,
    SearchResponse,
)
from reposcope.adapters.postgres_agent import AgentPreparation
from reposcope.adapters.source_storage import SourceStore
from reposcope.application.retrieval import RetrievalService
from reposcope.domain.errors import WorkError


def _bounded_text(value: str, characters: int = 12000, tokens: int = 4000) -> tuple[str, bool]:
    encoding = tiktoken.get_encoding("cl100k_base")
    clipped = value[:characters]
    encoded = encoding.encode(clipped)
    if len(encoded) > tokens:
        clipped = encoding.decode(encoded[:tokens])
    return clipped, clipped != value


class AgentTools:
    """The lease event is authoritative; model-supplied scope may only match it."""

    def __init__(
        self,
        principal_id: UUID,
        repository_id: UUID,
        generation_id: UUID,
        commit_sha: str,
        preparation: AgentPreparation,
        retrieval: RetrievalService,
        store: SourceStore,
    ) -> None:
        self.principal_id = principal_id
        self.repository_id = repository_id
        self.generation_id = generation_id
        self.commit_sha = commit_sha
        self.preparation = preparation
        self.retrieval = retrieval
        self.store = store
        self.evidence_tokens = 0
        self.evidence_chunks: set[UUID] = set()

    def _check(self, repository_id: UUID, generation_id: UUID) -> None:
        if (repository_id, generation_id) != (self.repository_id, self.generation_id):
            raise WorkError("FORBIDDEN")

    async def search_code(self, request: SearchCodeTool) -> SearchResponse:
        self._check(request.repository_id, request.generation_id)
        response = await self.retrieval.search_pinned(
            SearchRequest(
                repository_id=self.repository_id,
                query=request.query,
                top_k=min(request.top_k, 12),
                language=request.language,
                path_prefix=request.path_prefix,
            ),
            self.principal_id,
            self.generation_id,
            self.commit_sha,
        )
        total_tokens = 0
        total_characters = 0
        bounded = []
        encoding = tiktoken.get_encoding("cl100k_base")
        for match in response.results[:12]:
            if match.chunk_id in self.evidence_chunks:
                continue
            if match.chunk_id not in self.evidence_chunks and len(self.evidence_chunks) >= 12:
                break
            remaining_chars = 12000 - total_characters
            remaining_tokens = min(4000 - total_tokens, 8000 - self.evidence_tokens)
            if remaining_chars < 1 or remaining_tokens < 1:
                break
            content, _ = _bounded_text(match.content, remaining_chars, remaining_tokens)
            count = len(encoding.encode(content))
            if not content or total_tokens + count > 4000:
                break
            bounded.append(match.model_copy(update={"content": content}))
            total_tokens += count
            total_characters += len(content)
            self.evidence_tokens += count
            self.evidence_chunks.add(match.chunk_id)
        return response.model_copy(update={"results": bounded})

    def add_expanded(
        self, response: SearchResponse, candidates: tuple[SearchMatch, ...]
    ) -> SearchResponse:
        """Apply the same cumulative evidence budget to direct dependency chunks."""
        bounded = list(response.results)
        encoding = tiktoken.get_encoding("cl100k_base")
        for match in candidates[:4]:
            if match.chunk_id in self.evidence_chunks or len(self.evidence_chunks) >= 12:
                continue
            remaining = 8000 - self.evidence_tokens
            if remaining < 1:
                break
            content, _ = _bounded_text(match.content, 12000, min(remaining, 4000))
            if not content:
                continue
            bounded.append(match.model_copy(update={"content": content}))
            self.evidence_tokens += len(encoding.encode(content))
            self.evidence_chunks.add(match.chunk_id)
        return response.model_copy(update={"results": bounded})

    async def get_file(self, request: GetFileTool) -> FileResult:
        self._check(request.repository_id, request.generation_id)
        source_file = next(
            (
                item
                for item in self.preparation.snapshot.manifest.files
                if item.path == request.path
            ),
            None,
        )
        if source_file is None:
            raise WorkError("NOT_FOUND")
        raw = await asyncio.to_thread(self.store.read_blob, self.preparation.snapshot, source_file)
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            raise WorkError("VALIDATION_ERROR") from None
        if request.start_line > len(lines):
            raise WorkError("VALIDATION_ERROR")
        end = min(request.end_line, len(lines))
        remaining_tokens = min(4000, 8000 - self.evidence_tokens)
        if remaining_tokens < 1:
            raise WorkError("BUDGET_EXCEEDED")
        content, truncated = await asyncio.to_thread(
            _bounded_text,
            "\n".join(lines[request.start_line - 1 : end]),
            12000,
            remaining_tokens,
        )
        used = len(tiktoken.get_encoding("cl100k_base").encode(content))
        self.evidence_tokens += used
        actual_end = min(end, request.start_line + content.count("\n"))
        return FileResult(
            repository_id=self.repository_id,
            generation_id=self.generation_id,
            commit_sha=self.commit_sha,
            path=request.path,
            start_line=request.start_line,
            end_line=actual_end,
            content=content,
            truncated=truncated or end < request.end_line,
        )

    def get_repository_summary(self, repository_id: UUID, generation_id: UUID) -> RepositorySummary:
        self._check(repository_id, generation_id)
        return RepositorySummary(
            repository_id=self.repository_id,
            generation_id=self.generation_id,
            commit_sha=self.commit_sha,
            file_count=len(self.preparation.snapshot.manifest.files),
            chunk_count=self.preparation.chunk_count,
            languages=list(self.preparation.languages[:32]),
            overview=(
                "Indexed, immutable source snapshot available through scoped search and file tools."
            ),
        )
