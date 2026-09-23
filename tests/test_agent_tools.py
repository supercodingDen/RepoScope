"""Agent tools cannot escape the admitted source snapshot."""

from __future__ import annotations

import hashlib
from typing import cast
from uuid import uuid4

import pytest

from contracts.models import GetFileTool, SearchCodeTool, SearchResponse
from reposcope.adapters.postgres_agent import AgentPreparation
from reposcope.adapters.source_storage import SourceStore
from reposcope.application.agent_tools import AgentTools
from reposcope.application.retrieval import RetrievalService
from reposcope.domain.errors import WorkError
from reposcope.domain.source_snapshot import SourceFile, SourceManifest, SourceSnapshot


class FakeStore:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def read_blob(self, snapshot: SourceSnapshot, file: SourceFile) -> bytes:
        self.calls += 1
        assert file in snapshot.manifest.files
        assert hashlib.sha256(self.content).hexdigest() == file.sha256
        return self.content


class FakeRetrieval:
    async def search_pinned(
        self, request: object, principal_id: object, generation_id: object, commit_sha: object
    ) -> SearchResponse:
        raise AssertionError("No retrieval should occur for forged scope")


def fixtures(content: bytes | None = None) -> tuple[AgentTools, FakeStore]:
    content = content if content is not None else ("one\ntwo\n" * 150).encode()
    file = SourceFile("src/a.py", hashlib.sha256(content).hexdigest(), len(content))
    manifest = SourceManifest("local:test", "a" * 40, (file,), {}, 1, len(content), ())
    snapshot = SourceSnapshot(manifest, "snapshots/safe")
    store = FakeStore(content)
    tools = AgentTools(
        uuid4(),
        uuid4(),
        uuid4(),
        "a" * 40,
        AgentPreparation("Where?", snapshot, 12, ("python",)),
        cast(RetrievalService, FakeRetrieval()),
        cast(SourceStore, store),
    )
    return tools, store


@pytest.mark.asyncio
async def test_forged_scope_is_rejected_before_source_or_retrieval_io() -> None:
    tools, store = fixtures()
    with pytest.raises(WorkError) as forbidden:
        await tools.get_file(
            GetFileTool(
                repository_id=uuid4(),
                generation_id=tools.generation_id,
                path="src/a.py",
                end_line=3,
            )
        )
    assert forbidden.value.code == "FORBIDDEN"
    with pytest.raises(WorkError):
        await tools.search_code(
            SearchCodeTool(
                repository_id=tools.repository_id,
                generation_id=uuid4(),
                query="one",
            )
        )
    assert store.calls == 0


@pytest.mark.asyncio
async def test_file_read_is_bounded_to_manifest_path_and_requested_lines() -> None:
    tools, store = fixtures()
    result = await tools.get_file(
        GetFileTool(
            repository_id=tools.repository_id,
            generation_id=tools.generation_id,
            path="src/a.py",
            start_line=2,
            end_line=4,
        )
    )
    assert result.content == "two\none\ntwo"
    assert result.commit_sha == "a" * 40
    assert store.calls == 1
    with pytest.raises(WorkError) as missing:
        await tools.get_file(
            GetFileTool(
                repository_id=tools.repository_id,
                generation_id=tools.generation_id,
                path="src/other.py",
                end_line=2,
            )
        )
    assert missing.value.code == "NOT_FOUND"
    assert store.calls == 1


def test_summary_uses_pinned_metadata_only() -> None:
    tools, _ = fixtures()
    summary = tools.get_repository_summary(tools.repository_id, tools.generation_id)
    assert summary.file_count == 1
    assert summary.chunk_count == 12
    with pytest.raises(WorkError):
        tools.get_repository_summary(uuid4(), tools.generation_id)


@pytest.mark.asyncio
async def test_evidence_budget_and_clipped_file_range_hold_across_reads() -> None:
    tools, _ = fixtures((("x" * 100 + "\n") * 200).encode())
    first = await tools.get_file(
        GetFileTool(
            repository_id=tools.repository_id,
            generation_id=tools.generation_id,
            path="src/a.py",
            start_line=1,
            end_line=200,
        )
    )
    assert first.truncated
    assert first.end_line < 200
    assert first.end_line == 1 + first.content.count("\n")
    tools.evidence_tokens = 8000
    with pytest.raises(WorkError) as exhausted:
        await tools.get_file(
            GetFileTool(
                repository_id=tools.repository_id,
                generation_id=tools.generation_id,
                path="src/a.py",
                end_line=2,
            )
        )
    assert exhausted.value.code == "BUDGET_EXCEEDED"
