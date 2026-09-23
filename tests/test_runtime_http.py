"""ASGI health and error contracts for the T02 runtime."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from reposcope.runtime import RuntimeResources
from reposcope.transport.http.app import create_health_application


class ReadyProbe:
    """Minimal ready probe for HTTP contract tests."""

    async def database_migrated(self, version: str) -> bool:
        return True

    async def redis_available(self) -> bool:
        return True

    async def jetstream_available(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class UnreadyProbe(ReadyProbe):
    """Minimal unready probe for readiness failure contract tests."""

    async def redis_available(self) -> bool:
        return False


async def request(
    app: FastAPI, path: str, request_id: str | None = None, method: str = "GET"
) -> httpx.Response:
    """Issue one in-process ASGI request without an external server."""
    headers = {"X-Request-ID": request_id} if request_id is not None else {}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


@pytest.mark.asyncio
async def test_health_is_live_while_readiness_reports_dependency_outage() -> None:
    """A process can be alive while it is not safe to receive traffic."""
    app = create_health_application(
        RuntimeResources(probe=UnreadyProbe(), probe_timeout_seconds=0.1), include_metrics=False
    )

    health = await request(app, "/healthz")
    readiness = await request(app, "/readyz", "d34db33f-0f4f-4093-98ea-7f5fa936c69a")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert readiness.status_code == 503
    assert readiness.headers["content-type"].startswith("application/problem+json")
    assert readiness.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert readiness.json()["request_id"] == "d34db33f-0f4f-4093-98ea-7f5fa936c69a"


@pytest.mark.asyncio
async def test_unhandled_error_has_a_safe_problem_body_and_request_id() -> None:
    """Unexpected errors are mapped once and do not expose their original message."""
    app = create_health_application(
        RuntimeResources(probe=ReadyProbe(), probe_timeout_seconds=0.1), include_metrics=False
    )

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("postgresql://user:secret@database/private")

    response = await request(app, "/boom")
    body = response.json()

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["code"] == "INTERNAL_ERROR"
    assert "postgresql://" not in body["detail"]
    UUID(body["request_id"])
    assert response.headers["X-Request-ID"] == body["request_id"]


@pytest.mark.asyncio
async def test_health_rejects_an_unsupported_method_with_canonical_allow_response() -> None:
    """Health endpoints preserve protocol-level method semantics and their Allow header."""
    app = create_health_application(
        RuntimeResources(probe=ReadyProbe(), probe_timeout_seconds=0.1), include_metrics=False
    )

    response = await request(app, "/healthz", method="POST")

    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"
