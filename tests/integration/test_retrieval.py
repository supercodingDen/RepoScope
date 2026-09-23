"""T07 real PostgreSQL scope, filter and citation acceptance."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from contracts.models import SearchRequest
from reposcope.adapters.embedding import MockEmbeddingProvider
from reposcope.adapters.postgres_index import PostgresIndexRepository
from reposcope.adapters.postgres_retrieval import PostgresRetrievalRepository
from reposcope.adapters.postgres_work import PostgresWorkRepository
from reposcope.application.index import IndexHandler
from reposcope.application.retrieval import RetrievalService
from reposcope.application.work import WorkService
from reposcope.domain.delivery import Lease, Staged
from reposcope.domain.errors import WorkError
from reposcope.runtime import RuntimeResources
from reposcope.transport.http.app import create_public_application
from tests.integration.test_index import staged_files
from tests.integration.test_work_persistence import DatabaseHarness, ReadyProbe, database

pytestmark = pytest.mark.integration
__all__ = ["database"]


@pytest.mark.asyncio
async def test_search_ready_generation_filters_literal_paths_and_cites_source(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, event = await staged_files(
        database,
        tmp_path,
        {
            "src/a%/needle.py": b"def rare_needle():\n    return 42\n",
            "src/away/needle.py": b"def rare_needle():\n    return 43\n",
            "src/a%/other.ts": b"export const rare_needle = 44;\n",
        },
    )
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
    request = SearchRequest(
        repository_id=event.payload.repository_id,
        query="rare_needle",
        path_prefix="src/a%",
        language="python",
    )
    result = await service.search(request, database.principal)
    assert [item.path for item in result.results] == ["src/a%/needle.py"]
    assert result.commit_sha == event.payload.commit_sha
    assert result.results[0].start_line == 1
    assert result.results[0].end_line == 2
    assert (
        result.results[0].chunk_id
        == (await service.search(request, database.principal)).results[0].chunk_id
    )
    scope = await repository.active_scope(database.principal, event.payload.repository_id)
    assert scope is not None
    exact, lexical = await repository.candidates(
        scope, (1.0,) + (0.0,) * 383, "rare_needle", "python", "src/a%", exact=True
    )
    assert len(exact) == 1 and len(lexical) == 1
    typed = await service.search(
        SearchRequest(
            repository_id=event.payload.repository_id,
            query="rare_needle",
            path_prefix="src/a%",
            language="typescript",
        ),
        database.principal,
    )
    assert [item.path for item in typed.results] == ["src/a%/other.ts"]
    app = create_public_application(
        RuntimeResources(ReadyProbe(), 0.1),
        database.settings,
        WorkService(PostgresWorkRepository(database.pool)),
        service,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        response = await http.post(
            "/v1/search",
            headers={"Authorization": "Bearer synthetic-test-token"},
            json=request.model_dump(mode="json"),
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["path"] == "src/a%/needle.py"
    with pytest.raises(WorkError) as foreign:
        await service.search(request, uuid4())
    assert foreign.value.code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_accepted_but_unindexed_repository_is_not_ready(database: DatabaseHarness) -> None:
    accepted = await database.client.post(
        "/v1/repositories",
        headers={"Idempotency-Key": "not-ready"},
        json={"url": "https://github.com/example/unindexed"},
    )
    assert accepted.status_code == 202
    service = RetrievalService(PostgresRetrievalRepository(database.pool), MockEmbeddingProvider())
    with pytest.raises(WorkError) as error:
        await service.search(
            SearchRequest(repository_id=UUID(accepted.json()["repository_id"]), query="needle"),
            database.principal,
        )
    assert error.value.code == "INDEX_NOT_READY"


@pytest.mark.asyncio
async def test_narrow_filter_uses_only_active_generation_with_exact_recall(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    for key, files in (
        ("old", {"src/target.py": b"def obsolete_marker():\n    return 1\n"}),
        ("new", {"src/target.py": b"def current_marker():\n    return 2\n"}),
    ):
        delivery, store, event = await staged_files(database, tmp_path / key, files, key)
        lease = await delivery.claim(event, "source", uuid4())
        assert isinstance(lease, Lease)
        assert isinstance(
            await IndexHandler(
                PostgresIndexRepository(delivery), store, MockEmbeddingProvider()
            ).handle(lease),
            Staged,
        )
    repository = PostgresRetrievalRepository(database.pool)
    scope = await repository.active_scope(database.principal, event.payload.repository_id)
    assert scope is not None and scope.generation_id == event.payload.generation_id
    vector = (1.0,) + (0.0,) * 383
    approximate, _ = await repository.candidates(scope, vector, "marker", "python", "src/target.py")
    exact, _ = await repository.candidates(
        scope, vector, "marker", "python", "src/target.py", exact=True
    )
    assert approximate == exact
    assert len(approximate) == 1
    assert "current_marker" in approximate[0].content
