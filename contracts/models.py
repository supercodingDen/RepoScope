"""Canonical v1 HTTP, event, and agent-tool contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    field_validator,
    model_validator,
)

CommitSHA = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
SafePath = Annotated[str, StringConstraints(min_length=1, max_length=512)]
JobStatus = Literal["queued", "running", "succeeded", "failed"]
ErrorCode = Literal[
    "VALIDATION_ERROR",
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "NOT_FOUND",
    "METHOD_NOT_ALLOWED",
    "IDEMPOTENCY_CONFLICT",
    "INDEX_NOT_READY",
    "EVENT_CURSOR_EXPIRED",
    "PAYLOAD_TOO_LARGE",
    "RATE_LIMITED",
    "BUDGET_EXCEEDED",
    "DEPENDENCY_UNAVAILABLE",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_TIMEOUT",
    "INTERNAL_ERROR",
]
ERROR_STATUS: dict[str, int] = {
    "VALIDATION_ERROR": 422,
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "IDEMPOTENCY_CONFLICT": 409,
    "INDEX_NOT_READY": 409,
    "EVENT_CURSOR_EXPIRED": 410,
    "PAYLOAD_TOO_LARGE": 413,
    "RATE_LIMITED": 429,
    "BUDGET_EXCEEDED": 429,
    "DEPENDENCY_UNAVAILABLE": 503,
    "PROVIDER_UNAVAILABLE": 503,
    "PROVIDER_TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
}


def validate_relative_path(value: str) -> str:
    """Reject unsafe wire paths; filesystem containment still requires runtime checks."""
    if (
        value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or ":" in value
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Path must be a safe repository-relative path")
    return value


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Problem(Contract):
    type: Literal["about:blank"] = "about:blank"
    title: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    status: Annotated[int, Field(ge=400, le=599)]
    detail: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    code: ErrorCode
    request_id: UUID

    @model_validator(mode="after")
    def valid_status(self) -> Self:
        if ERROR_STATUS[self.code] != self.status:
            raise ValueError("Error code and HTTP status must agree")
        return self


class RepositoryCreate(Contract):
    url: Annotated[
        str,
        StringConstraints(
            max_length=256,
            pattern=r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$",
        ),
    ]
    requested_ref: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"),
    ] = "HEAD"

    @field_validator("url")
    @classmethod
    def canonical_source(cls, value: str) -> str:
        name = value.rsplit("/", 1)[1]
        if name in {".", ".."} or name.casefold().endswith(".git"):
            raise ValueError("Use a canonical public repository identity")
        return value

    @field_validator("requested_ref")
    @classmethod
    def safe_ref(cls, value: str) -> str:
        if (
            ".." in value
            or "//" in value
            or value.endswith(("/", ".", ".lock"))
            or any(part.startswith(".") for part in value.split("/"))
        ):
            raise ValueError("Invalid repository reference")
        return value


class RepositoryAccepted(Contract):
    repository_id: UUID
    job_id: UUID
    status: Literal["queued"] = "queued"


class JobView(Contract):
    job_id: UUID
    repository_id: UUID
    status: JobStatus
    attempts: Annotated[int, Field(ge=0, le=5)]
    progress_percent: Annotated[int, Field(ge=0, le=100)]
    commit_sha: CommitSHA | None
    failure_code: Annotated[str, StringConstraints(max_length=80)] | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def terminal_consistency(self) -> Self:
        if self.status == "failed" and self.failure_code is None:
            raise ValueError("Failed jobs require a failure code")
        if self.status != "failed" and self.failure_code is not None:
            raise ValueError("Only failed jobs expose a failure code")
        if self.status == "succeeded" and (self.progress_percent != 100 or self.commit_sha is None):
            raise ValueError("Successful jobs require a pinned commit and complete progress")
        if self.updated_at < self.created_at:
            raise ValueError("Updated time precedes creation")
        return self


class SearchRequest(Contract):
    repository_id: UUID
    query: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    top_k: Annotated[int, Field(ge=1, le=20)] = 10
    language: Literal["python", "typescript", "javascript", "go", "text"] | None = None
    path_prefix: Annotated[str, StringConstraints(max_length=512)] | None = None

    @field_validator("path_prefix")
    @classmethod
    def safe_prefix(cls, value: str | None) -> str | None:
        return validate_relative_path(value) if value is not None else None


class Citation(Contract):
    chunk_id: UUID
    repository_id: UUID
    generation_id: UUID
    commit_sha: CommitSHA
    path: SafePath
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return validate_relative_path(value)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("End line must not precede start line")
        return self


class SearchMatch(Citation):
    score: Annotated[FiniteFloat, Field(ge=0)]
    content: Annotated[str, StringConstraints(min_length=1, max_length=12000)]


class SearchResponse(Contract):
    repository_id: UUID
    generation_id: UUID
    commit_sha: CommitSHA
    results: Annotated[list[SearchMatch], Field(max_length=20)]
    duration_ms: Annotated[FiniteFloat, Field(ge=0)]

    @model_validator(mode="after")
    def same_snapshot(self) -> Self:
        for result in self.results:
            if (result.repository_id, result.generation_id, result.commit_sha) != (
                self.repository_id,
                self.generation_id,
                self.commit_sha,
            ):
                raise ValueError("Search results must belong to the requested snapshot")
        return self


class RunCreate(Contract):
    repository_id: UUID
    question: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class RunAccepted(Contract):
    run_id: UUID
    repository_id: UUID
    generation_id: UUID
    status: Literal["queued"] = "queued"


class RunResult(Contract):
    answer: Annotated[str, StringConstraints(min_length=1, max_length=16000)]
    citations: Annotated[list[Citation], Field(max_length=20)]
    evidence_status: Literal["supported", "insufficient"]
    model: Literal["mock", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
    estimated_cost_usd: Annotated[str, StringConstraints(pattern=r"^\d+\.\d{6}$")]

    @model_validator(mode="after")
    def evidence_present(self) -> Self:
        if self.evidence_status == "supported" and not self.citations:
            raise ValueError("Supported answers require source citations")
        return self


class RunView(Contract):
    run_id: UUID
    repository_id: UUID
    generation_id: UUID
    status: JobStatus
    result: RunResult | None
    failure_code: Annotated[str, StringConstraints(max_length=80)] | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def valid_result(self) -> Self:
        if (self.status == "succeeded") != (self.result is not None):
            raise ValueError("Only successful runs carry a final result")
        if (self.status == "failed") != (self.failure_code is not None):
            raise ValueError("Only failed runs carry a failure code")
        if self.updated_at < self.created_at:
            raise ValueError("Updated time precedes creation")
        if self.result:
            for citation in self.result.citations:
                if (citation.repository_id, citation.generation_id) != (
                    self.repository_id,
                    self.generation_id,
                ):
                    raise ValueError("Run citations must match the pinned generation")
        return self


class Health(Contract):
    status: Literal["ok", "degraded"]


class EventBase(Contract):
    event_id: UUID
    schema_version: Literal[1] = 1
    occurred_at: AwareDatetime
    aggregate_id: UUID
    trace_id: UUID


class IngestPayload(Contract):
    job_id: UUID
    repository_id: UUID
    requested_ref: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    principal_id: UUID


class IngestRequested(EventBase):
    event_type: Literal["repo.ingest.requested"] = "repo.ingest.requested"
    payload: IngestPayload

    @model_validator(mode="after")
    def correct_aggregate(self) -> Self:
        if self.aggregate_id != self.payload.job_id:
            raise ValueError("Ingestion aggregate must equal job ID")
        return self


class SourceAcquiredPayload(Contract):
    job_id: UUID
    repository_id: UUID
    generation_id: UUID
    principal_id: UUID
    commit_sha: CommitSHA
    manifest_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    policy_version: Literal["source-v1"] = "source-v1"


class SourceAcquired(EventBase):
    event_type: Literal["repo.source.acquired"] = "repo.source.acquired"
    payload: SourceAcquiredPayload

    @model_validator(mode="after")
    def correct_aggregate(self) -> Self:
        if self.aggregate_id != self.payload.job_id:
            raise ValueError("Source aggregate must equal job ID")
        return self


class AgentPayload(Contract):
    run_id: UUID
    repository_id: UUID
    generation_id: UUID
    commit_sha: CommitSHA
    principal_id: UUID
    policy_version: Literal["routing-v1"] = "routing-v1"


class AgentRequested(EventBase):
    event_type: Literal["agent.run.requested"] = "agent.run.requested"
    payload: AgentPayload

    @model_validator(mode="after")
    def correct_aggregate(self) -> Self:
        if self.aggregate_id != self.payload.run_id:
            raise ValueError("Agent aggregate must equal run ID")
        return self


class StartedData(Contract):
    kind: Literal["run.started"] = "run.started"
    model: Literal["mock", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]


class ToolData(Contract):
    kind: Literal["tool.started", "tool.completed"]
    tool: Literal["search_code", "get_file", "get_repository_summary"]
    step: Annotated[int, Field(ge=1, le=6)]


class CompletedData(Contract):
    kind: Literal["run.completed"] = "run.completed"
    result: RunResult


class FailedData(Contract):
    kind: Literal["run.failed"] = "run.failed"
    code: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class RunEvent(Contract):
    run_id: UUID
    sequence: Annotated[int, Field(ge=1)]
    occurred_at: AwareDatetime
    data: Annotated[
        StartedData | ToolData | CompletedData | FailedData, Field(discriminator="kind")
    ]


class PinnedScope(Contract):
    repository_id: UUID
    generation_id: UUID


class SearchCodeTool(SearchRequest):
    generation_id: UUID


class GetFileTool(PinnedScope):
    path: SafePath
    start_line: Annotated[int, Field(ge=1)] = 1
    end_line: Annotated[int, Field(ge=1)]

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return validate_relative_path(value)

    @model_validator(mode="after")
    def bounded_range(self) -> Self:
        if not self.start_line <= self.end_line < self.start_line + 200:
            raise ValueError("File requests must contain between 1 and 200 lines")
        return self


class FileResult(PinnedScope):
    commit_sha: CommitSHA
    path: SafePath
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]
    content: Annotated[str, StringConstraints(max_length=12000)]
    truncated: bool

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return validate_relative_path(value)

    @model_validator(mode="after")
    def bounded_range(self) -> Self:
        if not self.start_line <= self.end_line < self.start_line + 200:
            raise ValueError("File results must contain between 1 and 200 lines")
        return self


class RepositorySummary(PinnedScope):
    commit_sha: CommitSHA
    file_count: Annotated[int, Field(ge=0)]
    chunk_count: Annotated[int, Field(ge=0)]
    languages: Annotated[list[str], Field(max_length=32)]
    overview: Annotated[str, StringConstraints(max_length=4000)]


MODELS: dict[str, type[Contract]] = {
    model.__name__: model
    for model in (
        Problem,
        RepositoryCreate,
        RepositoryAccepted,
        JobView,
        SearchRequest,
        SearchResponse,
        RunCreate,
        RunAccepted,
        RunResult,
        RunView,
        Health,
        IngestRequested,
        SourceAcquired,
        AgentRequested,
        RunEvent,
        SearchCodeTool,
        GetFileTool,
        PinnedScope,
        FileResult,
        RepositorySummary,
    )
}
