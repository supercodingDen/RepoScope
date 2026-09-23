"""Private Prometheus metrics with fixed, low-cardinality labels."""

from __future__ import annotations

import re
from typing import Literal

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "reposcope_http_requests_total", "Public API request count", ("route", "method", "status")
)
HTTP_DURATION = Histogram(
    "reposcope_http_response_seconds",
    "Time to public API response headers",
    ("route", "method"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
ADMISSION_REJECTIONS = Counter(
    "reposcope_admission_rejections_total", "Rejected work admissions", ("reason",)
)
DEPENDENCY_READY = Gauge(
    "reposcope_dependency_ready", "Most recent bounded readiness probe", ("dependency",)
)
DELIVERY_OUTCOMES = Counter(
    "reposcope_delivery_outcomes_total", "Worker message outcomes", ("consumer", "outcome")
)
PUBLISH_OUTCOMES = Counter(
    "reposcope_outbox_publish_outcomes_total", "Outbox publication outcomes", ("outcome",)
)
WORK_BACKLOG = Gauge("reposcope_work_backlog", "Most recent durable work snapshot", ("kind",))
SNAPSHOT_UP = Gauge("reposcope_work_snapshot_up", "Whether the most recent work snapshot succeeded")

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_ROUTES = {
    "/v1/repositories": "/v1/repositories",
    "/v1/runs": "/v1/runs",
    "/v1/search": "/v1/search",
}


def canonical_route(path: str) -> str:
    """Map client paths to a finite label set; never publish raw identifiers."""
    if path in _ROUTES:
        return _ROUTES[path]
    if re.fullmatch(rf"/v1/jobs/{_UUID}", path):
        return "/v1/jobs/{job_id}"
    if re.fullmatch(rf"/v1/runs/{_UUID}/events", path):
        return "/v1/runs/{run_id}/events"
    if re.fullmatch(rf"/v1/runs/{_UUID}", path):
        return "/v1/runs/{run_id}"
    return "unmatched"


def observe_http(path: str, method: str, status: int, seconds: float) -> None:
    """Record one request using only finite metric labels."""
    route = canonical_route(path)
    safe_method = method if method in {"GET", "POST"} else "OTHER"
    safe_status = str(status) if 100 <= status <= 599 else "other"
    HTTP_REQUESTS.labels(route=route, method=safe_method, status=safe_status).inc()
    HTTP_DURATION.labels(route=route, method=safe_method).observe(max(0, seconds))


def observe_admission_rejection(reason: Literal["capacity", "budget", "dependency"]) -> None:
    ADMISSION_REJECTIONS.labels(reason=reason).inc()


def observe_delivery(
    consumer: str,
    outcome: Literal[
        "completed",
        "failed",
        "staged",
        "deferred",
        "retry",
        "duplicate",
        "quarantined",
        "lease_lost",
        "cancelled",
    ],
) -> None:
    safe_consumer = consumer if consumer in {"indexer", "source", "agent"} else "other"
    DELIVERY_OUTCOMES.labels(consumer=safe_consumer, outcome=outcome).inc()


def observe_publication(outcome: Literal["published", "retry"]) -> None:
    PUBLISH_OUTCOMES.labels(outcome=outcome).inc()
