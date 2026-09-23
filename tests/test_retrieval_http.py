"""Public T07 search authentication and wire delegation."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from contracts.models import SearchResponse
from reposcope.application.work import WorkService
from reposcope.runtime import RuntimeResources
from reposcope.transport.http.app import create_public_application
from tests.test_work_http import Probe, TestRepository, settings


class SearchSpy:
    def __init__(self) -> None:
        self.principal: UUID | None = None

    async def search(self, request: object, principal_id: UUID) -> SearchResponse:
        self.principal = principal_id
        return SearchResponse(
            repository_id=uuid4(),
            generation_id=uuid4(),
            commit_sha="a" * 40,
            results=[],
            duration_ms=1.0,
        )


@pytest.mark.asyncio
async def test_public_search_requires_auth_and_uses_server_principal() -> None:
    spy = SearchSpy()
    app = create_public_application(
        RuntimeResources(Probe(), 0.1), settings(), WorkService(TestRepository()), spy
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        payload = {"repository_id": str(uuid4()), "query": "needle"}
        assert (await client.post("/v1/search", json=payload)).status_code == 401
        response = await client.post(
            "/v1/search",
            headers={"Authorization": "Bearer test-token", "X-Principal-ID": str(uuid4())},
            json=payload,
        )
        assert response.status_code == 200
        assert spy.principal == settings().principal_id
        assert SearchResponse.model_validate_json(response.content).results == []
