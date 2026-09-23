"""T10 observability never exposes unbounded labels or secret-bearing logs."""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from reposcope.application.work import AdmissionPolicy
from reposcope.domain.errors import WorkError
from reposcope.logging_config import JsonLogFormatter
from reposcope.metrics import (
    ADMISSION_REJECTIONS,
    DEPENDENCY_READY,
    HTTP_REQUESTS,
    canonical_route,
)
from reposcope.runtime import RuntimeResources
from reposcope.transport.http.app import create_health_application


def test_route_labels_hide_identifiers_and_unmatched_paths() -> None:
    assert canonical_route("/v1/runs/" + str(uuid4())) == "/v1/runs/{run_id}"
    assert canonical_route("/v1/jobs/" + str(uuid4())) == "/v1/jobs/{job_id}"
    assert canonical_route("/v1/runs/user-supplied-secret/events") == "unmatched"


def test_json_logs_emit_only_safe_symbols_and_validated_fields() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        "reposcope.test",
        logging.ERROR,
        __file__,
        1,
        "postgresql://user:secret@database/private",
        (),
        None,
    )
    record.request_id = str(uuid4())
    record.error_code = "DEPENDENCY_UNAVAILABLE"
    record.run_id = "private prompt"
    rendered = formatter.format(record)
    assert "secret" not in rendered and "private prompt" not in rendered
    assert "external_log" in rendered and "DEPENDENCY_UNAVAILABLE" in rendered
    assert "request_id" in rendered


class DownProbe:
    async def database_migrated(self, version: str) -> bool:
        return True

    async def redis_available(self) -> bool:
        return False

    async def jetstream_available(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_readiness_exposes_bounded_component_gauges_privately() -> None:
    app = create_health_application(RuntimeResources(DownProbe(), 0.1), include_metrics=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
        metrics = await client.get("/metrics")
    assert response.status_code == 503
    assert DEPENDENCY_READY.labels(dependency="database")._value.get() == 1
    assert DEPENDENCY_READY.labels(dependency="redis")._value.get() == 0
    assert DEPENDENCY_READY.labels(dependency="jetstream")._value.get() == 1
    assert "reposcope_dependency_ready" in metrics.text
    assert "private prompt" not in metrics.text


def test_metric_families_have_fixed_label_dimensions() -> None:
    assert HTTP_REQUESTS._labelnames == ("route", "method", "status")
    assert ADMISSION_REJECTIONS._labelnames == ("reason",)


def test_default_admission_boundary_matches_deployment_limit() -> None:
    policy = AdmissionPolicy()
    policy.check(99, Decimal(0), Decimal(0))
    with pytest.raises(WorkError) as exhausted:
        policy.check(100, Decimal(0), Decimal(0))
    assert exhausted.value.code == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_http_metrics_count_safe_routes_and_admission_rejections() -> None:
    app = create_health_application(RuntimeResources(DownProbe(), 0.1), include_metrics=True)

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/repositories")
    async def reject() -> None:
        raise WorkError("RATE_LIMITED")

    identity = str(uuid4())
    before = HTTP_REQUESTS.labels(
        route="/v1/runs/{run_id}", method="GET", status="200"
    )._value.get()
    refused = ADMISSION_REJECTIONS.labels(reason="capacity")._value.get()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get(f"/v1/runs/{identity}")).status_code == 200
        assert (await client.post("/v1/repositories")).status_code == 429
        metrics = await client.get("/metrics")
    assert (
        HTTP_REQUESTS.labels(route="/v1/runs/{run_id}", method="GET", status="200")._value.get()
        == before + 1
    )
    assert ADMISSION_REJECTIONS.labels(reason="capacity")._value.get() == refused + 1
    assert identity not in metrics.text


@pytest.mark.asyncio
async def test_validation_and_missing_route_logs_carry_safe_request_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_health_application(RuntimeResources(DownProbe(), 0.1), include_metrics=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/v1/unknown")
        invalid_method = await client.post("/healthz")
    assert missing.status_code == 404 and invalid_method.status_code == 405
    logged = [
        record
        for record in caplog.records
        if record.name == "reposcope.http" and record.msg == "request_rejected"
    ]
    assert {getattr(record, "error_code", None) for record in logged} >= {
        "NOT_FOUND",
        "METHOD_NOT_ALLOWED",
    }
    assert all(UUID(str(getattr(record, "request_id", ""))) for record in logged)
    assert {getattr(record, "request_id", None) for record in logged} == {
        missing.headers["X-Request-ID"],
        invalid_method.headers["X-Request-ID"],
    }
