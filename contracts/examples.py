"""Non-sensitive deterministic examples shared by producers and consumers."""

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

REPO = "11111111-1111-4111-8111-111111111111"
JOB = "22222222-2222-4222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
GEN = "44444444-4444-4444-8444-444444444444"
EVENT = "55555555-5555-4555-8555-555555555555"
TRACE = "66666666-6666-4666-8666-666666666666"
PRINCIPAL = "77777777-7777-4777-8777-777777777777"
CHUNK = "88888888-8888-4888-8888-888888888888"
SHA = "0123456789abcdef0123456789abcdef01234567"
TIME = "2026-09-16T12:00:00Z"
CITATION: JsonObject = {
    "chunk_id": CHUNK,
    "repository_id": REPO,
    "generation_id": GEN,
    "commit_sha": SHA,
    "path": "src/retry.py",
    "start_line": 10,
    "end_line": 14,
}
RESULT: JsonObject = {
    "answer": "Retry handling is defined in src/retry.py, lines 10-14.",
    "citations": [CITATION],
    "evidence_status": "supported",
    "model": "mock",
    "estimated_cost_usd": "0.000000",
}

EXAMPLES: dict[str, JsonObject] = {
    "Problem": {
        "type": "about:blank",
        "title": "Invalid request",
        "status": 422,
        "detail": "The request does not match the contract.",
        "code": "VALIDATION_ERROR",
        "request_id": TRACE,
    },
    "RepositoryCreate": {"url": "https://github.com/psf/requests", "requested_ref": "HEAD"},
    "RepositoryAccepted": {"repository_id": REPO, "job_id": JOB, "status": "queued"},
    "JobView": {
        "job_id": JOB,
        "repository_id": REPO,
        "status": "succeeded",
        "attempts": 1,
        "progress_percent": 100,
        "commit_sha": SHA,
        "failure_code": None,
        "created_at": TIME,
        "updated_at": TIME,
    },
    "SearchRequest": {
        "repository_id": REPO,
        "query": "Where is retry implemented?",
        "top_k": 10,
        "language": "python",
        "path_prefix": "src/",
    },
    "SearchResponse": {
        "repository_id": REPO,
        "generation_id": GEN,
        "commit_sha": SHA,
        "results": [{**CITATION, "score": 0.032, "content": "def retry() -> None:\n    pass\n"}],
        "duration_ms": 12.5,
    },
    "RunCreate": {"repository_id": REPO, "question": "Explain the retry policy."},
    "RunAccepted": {"run_id": RUN, "repository_id": REPO, "generation_id": GEN, "status": "queued"},
    "RunResult": RESULT,
    "RunView": {
        "run_id": RUN,
        "repository_id": REPO,
        "generation_id": GEN,
        "status": "succeeded",
        "result": RESULT,
        "failure_code": None,
        "created_at": TIME,
        "updated_at": TIME,
    },
    "Health": {"status": "ok"},
    "IngestRequested": {
        "event_id": EVENT,
        "schema_version": 1,
        "occurred_at": TIME,
        "aggregate_id": JOB,
        "trace_id": TRACE,
        "event_type": "repo.ingest.requested",
        "payload": {
            "job_id": JOB,
            "repository_id": REPO,
            "requested_ref": "HEAD",
            "principal_id": PRINCIPAL,
        },
    },
    "SourceAcquired": {
        "event_id": EVENT,
        "schema_version": 1,
        "event_type": "repo.source.acquired",
        "occurred_at": TIME,
        "aggregate_id": JOB,
        "trace_id": TRACE,
        "payload": {
            "job_id": JOB,
            "repository_id": REPO,
            "generation_id": GEN,
            "principal_id": PRINCIPAL,
            "commit_sha": SHA,
            "manifest_digest": "a" * 64,
            "policy_version": "source-v1",
        },
    },
    "AgentRequested": {
        "event_id": EVENT,
        "schema_version": 1,
        "occurred_at": TIME,
        "aggregate_id": RUN,
        "trace_id": TRACE,
        "event_type": "agent.run.requested",
        "payload": {
            "run_id": RUN,
            "repository_id": REPO,
            "generation_id": GEN,
            "commit_sha": SHA,
            "principal_id": PRINCIPAL,
            "policy_version": "routing-v1",
        },
    },
    "RunEvent": {
        "run_id": RUN,
        "sequence": 1,
        "occurred_at": TIME,
        "data": {"kind": "run.started", "model": "mock"},
    },
    "SearchCodeTool": {"repository_id": REPO, "generation_id": GEN, "query": "retry", "top_k": 10},
    "GetFileTool": {
        "repository_id": REPO,
        "generation_id": GEN,
        "path": "src/retry.py",
        "start_line": 10,
        "end_line": 14,
    },
    "PinnedScope": {"repository_id": REPO, "generation_id": GEN},
    "FileResult": {
        "repository_id": REPO,
        "generation_id": GEN,
        "commit_sha": SHA,
        "path": "src/retry.py",
        "start_line": 10,
        "end_line": 14,
        "content": "def retry() -> None:\n    pass\n",
        "truncated": False,
    },
    "RepositorySummary": {
        "repository_id": REPO,
        "generation_id": GEN,
        "commit_sha": SHA,
        "file_count": 12,
        "chunk_count": 40,
        "languages": ["python"],
        "overview": "Example repository; fixture counts are not benchmarks.",
    },
}
