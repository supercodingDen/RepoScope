"""Thin FastAPI health controllers and safe error mapping."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from contracts.models import (
    ERROR_STATUS,
    ErrorCode,
    Health,
    JobView,
    Problem,
    RepositoryAccepted,
    RepositoryCreate,
    RunAccepted,
    RunCreate,
    RunView,
)
from reposcope.application.work import WorkService
from reposcope.domain.errors import WorkError
from reposcope.runtime import RuntimeResources
from reposcope.settings import RuntimeSettings

LOGGER = logging.getLogger("reposcope.http")
RequestHandler = Callable[[Request], Awaitable[Response]]


class BodyLimitMiddleware:
    """Bound bytes actually received, including requests without Content-Length."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > 65536:
                request = Request(scope)
                request.state.request_id = _request_id(request.headers.get("X-Request-ID"))
                response = _problem_response(
                    request,
                    status=413,
                    code="PAYLOAD_TOO_LARGE",
                    title="Payload too large",
                    detail="The request body exceeds 64 KiB.",
                )
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def buffered_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)


def create_public_application(
    resources: RuntimeResources,
    settings: RuntimeSettings,
    service: WorkService | None,
) -> FastAPI:
    """Register authenticated business controllers on the public application only."""
    application = create_health_application(resources, include_metrics=False)
    application.add_middleware(BodyLimitMiddleware)

    def authorized(request: Request) -> WorkService:
        values = request.headers.getlist("Authorization")
        token = settings.api_token.get_secret_value()
        scheme, _, supplied = (values[0] if len(values) == 1 else "").partition(" ")
        matches = secrets.compare_digest(supplied.encode("utf-8"), token.encode("utf-8"))
        if not token or scheme.lower() != "bearer" or not matches:
            raise WorkError("UNAUTHENTICATED")
        if service is None:
            raise WorkError("DEPENDENCY_UNAVAILABLE")
        return service

    def key(request: Request) -> str:
        values = request.headers.getlist("Idempotency-Key")
        if len(values) != 1:
            raise WorkError("VALIDATION_ERROR")
        return values[0]

    def identifier(value: str) -> UUID:
        try:
            return UUID(value)
        except ValueError:
            raise WorkError("VALIDATION_ERROR") from None

    @application.post("/v1/repositories", response_model=RepositoryAccepted, status_code=202)
    async def create_repository(request: Request) -> RepositoryAccepted:
        workflow = authorized(request)
        body = RepositoryCreate.model_validate_json(await request.body())
        return await workflow.create_repository(
            body, settings.principal_id, key(request), _request_id_from(request)
        )

    @application.get("/v1/jobs/{job_id}", response_model=JobView)
    async def get_job(job_id: str, request: Request) -> JobView:
        workflow = authorized(request)
        return await workflow.get_job(settings.principal_id, identifier(job_id))

    @application.post("/v1/runs", response_model=RunAccepted, status_code=202)
    async def create_run(request: Request) -> RunAccepted:
        workflow = authorized(request)
        body = RunCreate.model_validate_json(await request.body())
        return await workflow.create_run(
            body, settings.principal_id, key(request), _request_id_from(request)
        )

    @application.get("/v1/runs/{run_id}", response_model=RunView)
    async def get_run(run_id: str, request: Request) -> RunView:
        workflow = authorized(request)
        return await workflow.get_run(settings.principal_id, identifier(run_id))

    return application


def create_health_application(resources: RuntimeResources, *, include_metrics: bool) -> FastAPI:
    """Create a health-only application for public or private role endpoints."""
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    _install_request_context(application)
    _install_error_handlers(application)

    @application.get("/healthz", response_model=Health)
    async def health() -> Health:
        """Report that this process can answer requests."""
        return Health(status="ok")

    @application.get("/readyz", response_model=Health, responses={503: {"model": Problem}})
    async def ready(request: Request) -> Health | JSONResponse:
        """Report whether all dependencies can safely receive work."""
        if await resources.is_ready():
            return Health(status="ok")
        return _problem_response(
            request,
            status=503,
            code="DEPENDENCY_UNAVAILABLE",
            title="Dependency unavailable",
            detail="Required runtime dependencies are not ready.",
        )

    if include_metrics:

        @application.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            """Expose private Prometheus metrics for the role."""
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return application


def _install_request_context(application: FastAPI) -> None:
    """Attach one valid request identifier to each response and error."""

    @application.middleware("http")
    async def request_context(request: Request, call_next: RequestHandler) -> Response:
        request_id = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        return response


def _install_error_handlers(application: FastAPI) -> None:
    """Map transport failures to the canonical problem wire contract."""

    @application.exception_handler(WorkError)
    async def work_error(request: Request, error: WorkError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if error.code == "UNAUTHENTICATED" else None
        if error.code in {"RATE_LIMITED", "BUDGET_EXCEEDED"}:
            headers = {"Retry-After": "1"}
        return _problem_response(
            request,
            status=ERROR_STATUS[error.code],
            code=error.code,
            title=error.code.replace("_", " ").capitalize(),
            detail="The request could not be completed.",
            headers=headers,
        )

    @application.exception_handler(ValidationError)
    async def contract_validation_error(request: Request, _: ValidationError) -> JSONResponse:
        return _problem_response(
            request,
            status=422,
            code="VALIDATION_ERROR",
            title="Validation error",
            detail="The request is invalid.",
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        """Return a stable validation problem without echoing client input."""
        return _problem_response(
            request,
            status=422,
            code="VALIDATION_ERROR",
            title="Validation error",
            detail="The request is invalid.",
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        """Return a canonical missing-route response for this health-only surface."""
        if error.status_code == 404:
            return _problem_response(
                request,
                status=404,
                code="NOT_FOUND",
                title="Not found",
                detail="The requested resource was not found.",
                headers=error.headers,
            )
        if error.status_code == 405:
            return _problem_response(
                request,
                status=405,
                code="METHOD_NOT_ALLOWED",
                title="Method not allowed",
                detail="The requested method is not allowed for this resource.",
                headers=error.headers,
            )
        return _problem_response(
            request,
            status=500,
            code="INTERNAL_ERROR",
            title="Internal server error",
            detail="The request could not be completed.",
            headers=error.headers,
        )

    @application.exception_handler(Exception)
    async def internal_error(request: Request, _: Exception) -> JSONResponse:
        """Return a secret-safe unexpected-error response and structured log entry."""
        LOGGER.error(
            "unhandled_request",
            extra={"event": "unhandled_request", "request_id": str(_request_id_from(request))},
        )
        return _problem_response(
            request,
            status=500,
            code="INTERNAL_ERROR",
            title="Internal server error",
            detail="The request could not be completed.",
        )


def _problem_response(
    request: Request,
    *,
    status: int,
    code: ErrorCode,
    title: str,
    detail: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Serialize a validated canonical error response."""
    problem = Problem(
        title=title,
        status=status,
        detail=detail,
        code=code,
        request_id=_request_id_from(request),
    )
    response_headers = {"X-Request-ID": str(problem.request_id)}
    if headers is not None:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
        headers=response_headers,
    )


def _request_id(value: str | None) -> UUID:
    """Accept only a UUID request identifier supplied by the client."""
    if value is not None:
        try:
            return UUID(value)
        except ValueError:
            pass
    return uuid4()


def _request_id_from(request: Request) -> UUID:
    """Read the middleware request identifier or create one for early exceptions."""
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, UUID) else uuid4()
