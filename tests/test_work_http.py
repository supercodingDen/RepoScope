"""Offline HTTP security and error contracts with a typed repository double."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest

from contracts.models import (
    JobView,
    RepositoryAccepted,
    RepositoryCreate,
    RunAccepted,
    RunCreate,
    RunView,
)
from reposcope.application.work import AdmissionPolicy, Submission, WorkService
from reposcope.domain.errors import WorkError
from reposcope.runtime import RuntimeResources
from reposcope.settings import RuntimeSettings
from reposcope.transport.http.app import create_health_application, create_public_application


class TestRepository:
    """Observable delegation only; not a durable persistence implementation."""

    __test__ = False

    def __init__(self) -> None:
        self.calls = 0
        self.failure: BaseException | None = None
        self.principal: UUID | None = None

    async def create_repository(
        self, request: RepositoryCreate, submission: Submission, policy: AdmissionPolicy
    ) -> RepositoryAccepted:
        self.calls += 1
        self.principal = submission.principal_id
        if self.failure is not None:
            raise self.failure
        return RepositoryAccepted(repository_id=uuid4(), job_id=uuid4())

    async def create_run(
        self, request: RunCreate, submission: Submission, policy: AdmissionPolicy
    ) -> RunAccepted:
        raise WorkError("INDEX_NOT_READY")

    async def get_job(self, principal_id: UUID, job_id: UUID) -> JobView:
        raise WorkError("NOT_FOUND")

    async def get_run(self, principal_id: UUID, run_id: UUID) -> RunView:
        raise WorkError("NOT_FOUND")


class Probe:
    async def database_migrated(self, version: str) -> bool:
        return True

    async def redis_available(self) -> bool:
        return True

    async def jetstream_available(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def settings(token: str = "test-token") -> RuntimeSettings:
    return RuntimeSettings.from_values(
        {
            "DATABASE_URL": "postgresql://runtime:synthetic@localhost/test",
            "REDIS_URL": "redis://localhost/0",
            "NATS_URL": "nats://localhost:4222",
            "REPOSCOPE_API_TOKEN": token,
        }
    )


def client(repository: TestRepository, token: str = "test-token") -> httpx.AsyncClient:
    app = create_public_application(
        RuntimeResources(Probe(), 0.1), settings(token), WorkService(repository)
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_authentication_server_owned_identity_and_missing_token() -> None:
    repository = TestRepository()
    async with client(repository) as http:
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = await http.post("/v1/repositories", headers=headers, json={})
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
        response = await http.post(
            "/v1/repositories",
            headers={
                "Authorization": "Bearer test-token",
                "Idempotency-Key": "first",
                "X-Principal-ID": str(uuid4()),
            },
            json={"url": "https://github.com/example/repo"},
        )
        assert response.status_code == 202
        assert repository.principal == settings().principal_id
    async with client(repository, "") as http:
        assert (await http.get("/healthz")).status_code == 200
        assert (
            await http.get(f"/v1/jobs/{uuid4()}", headers={"Authorization": "Bearer test-token"})
        ).status_code == 401


@pytest.mark.asyncio
async def test_public_responses_do_not_cache_or_render_untrusted_content() -> None:
    repository = TestRepository()
    async with client(repository) as http:
        success = await http.post(
            "/v1/repositories",
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "secure-response"},
            json={"url": "https://github.com/example/repo"},
        )
        unauthorized = await http.get(f"/v1/jobs/{uuid4()}")
        oversized = await http.post("/v1/repositories", content=b"x" * 65537)
        for response in (success, unauthorized, oversized):
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Referrer-Policy"] == "no-referrer"
            assert response.headers["Content-Security-Policy"] == "default-src 'none'"


@pytest.mark.asyncio
async def test_public_surface_exposes_only_health_without_authentication() -> None:
    async with client(TestRepository()) as http:
        for path in ("/healthz", "/readyz"):
            assert (await http.get(path)).status_code == 200
        for path in ("/metrics", "/docs", "/redoc", "/openapi.json"):
            assert (await http.get(path)).status_code == 404
        for method, path in (
            ("POST", "/v1/repositories"),
            ("GET", f"/v1/jobs/{uuid4()}"),
            ("POST", "/v1/runs"),
            ("GET", f"/v1/runs/{uuid4()}"),
            ("GET", f"/v1/runs/{uuid4()}/events"),
            ("POST", "/v1/search"),
        ):
            response = await http.request(method, path)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,key",
    [
        (b'{"url":17}', "valid"),
        (b'{"url":"https://github.com/a/b","principal_id":"bad"}', "valid"),
        (b"{invalid", "valid"),
        (b'{"url":"https://github.com/a/b"}', ""),
        (b'{"url":"https://github.com/a/b"}', "has space"),
        (b'{"url":"https://github.com/a/b"}', "x" * 129),
    ],
)
async def test_invalid_requests_are_safe_and_do_not_delegate(body: bytes, key: str) -> None:
    repository = TestRepository()
    async with client(repository) as http:
        response = await http.post(
            "/v1/repositories",
            content=body,
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": key},
        )
    assert response.status_code == 422
    assert repository.calls == 0
    assert "github.com" not in response.text
    assert response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_streamed_body_is_bounded_without_content_length() -> None:
    repository = TestRepository()

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(70):
            yield b"x" * 1024

    async with client(repository) as http:
        response = await http.post("/v1/repositories", content=chunks())
    assert response.status_code == 413
    assert response.headers["X-Request-ID"]
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_classified_unexpected_and_validation_errors_are_safe() -> None:
    repository = TestRepository()
    async with client(repository) as http:
        for error, status in (
            (WorkError("DEPENDENCY_UNAVAILABLE"), 503),
            (RuntimeError("secret-dsn-and-question"), 500),
        ):
            repository.failure = error
            response = await http.post(
                "/v1/repositories",
                json={"url": "https://github.com/a/b"},
                headers={"Authorization": "Bearer test-token", "Idempotency-Key": "key"},
            )
            assert response.status_code == status
            assert "secret-dsn" not in response.text
        response = await http.get(
            "/v1/jobs/not-a-uuid", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 422
        assert (await http.put("/v1/repositories")).headers["Allow"] == "POST"
        assert (await http.get("/unknown")).status_code == 404


@pytest.mark.asyncio
async def test_cancellation_propagates_through_application_service() -> None:
    repository = TestRepository()
    service = WorkService(repository)

    repository.failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.create_repository(
            RepositoryCreate(url="https://github.com/a/b"), uuid4(), "key", uuid4()
        )


@pytest.mark.asyncio
async def test_exact_body_limit_and_declared_length_cannot_bypass_bound() -> None:
    repository = TestRepository()
    body = b'{"url":"https://github.com/a/b"}'
    async with client(repository) as http:
        response = await http.post(
            "/v1/repositories",
            content=body + b" " * (65536 - len(body)),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "boundary"},
        )
        assert response.status_code == 202
        response = await http.post(
            "/v1/repositories", content=b"x" * 65537, headers={"Content-Length": "1"}
        )
        assert response.status_code == 413
    assert repository.calls == 1


@pytest.mark.asyncio
async def test_duplicate_credentials_and_keys_are_rejected() -> None:
    repository = TestRepository()
    async with client(repository) as http:
        response = await http.post(
            "/v1/repositories",
            json={"url": "https://github.com/a/b"},
            headers=[
                ("Authorization", "Bearer test-token"),
                ("Authorization", "Bearer test-token"),
                ("Idempotency-Key", "key"),
            ],
        )
        assert response.status_code == 401
        response = await http.post(
            "/v1/repositories",
            json={"url": "https://github.com/a/b"},
            headers=[
                ("Authorization", "Bearer test-token"),
                ("Idempotency-Key", "key"),
                ("Idempotency-Key", "key"),
            ],
        )
        assert response.status_code == 422
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_management_has_no_business_routes() -> None:
    app = create_health_application(RuntimeResources(Probe(), 0.1), include_metrics=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        for route in ("/v1/repositories", "/v1/runs", f"/v1/jobs/{uuid4()}", f"/v1/runs/{uuid4()}"):
            assert (await http.get(route)).status_code == 404
