"""The public CLI flow works against REST and resumable SSE without providers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from scripts.demo import demonstrate


@pytest.mark.asyncio
async def test_demo_imports_waits_streams_and_prints_citations() -> None:
    repository_id, job_id, generation_id, run_id, chunk_id = (uuid4() for _ in range(5))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/repositories":
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(
                202, json={"repository_id": str(repository_id), "job_id": str(job_id)}
            )
        if request.url.path == f"/v1/jobs/{job_id}":
            return httpx.Response(200, json={"status": "succeeded"})
        if request.url.path == "/v1/runs":
            assert json.loads(request.content)["repository_id"] == str(repository_id)
            return httpx.Response(202, json={"run_id": str(run_id)})
        if request.url.path == f"/v1/runs/{run_id}/events":
            if "last-event-id" not in request.headers:
                return httpx.Response(
                    200, text=f"id: {run_id}:1\nevent: run.started\ndata: {{}}\n\n"
                )
            assert request.headers["last-event-id"] == f"{run_id}:1"
            event = {
                "data": {
                    "kind": "run.completed",
                    "result": {
                        "answer": "42",
                        "citations": [
                            {
                                "chunk_id": str(chunk_id),
                                "path": "src/answer.py",
                                "start_line": 1,
                                "end_line": 2,
                                "repository_id": str(repository_id),
                                "generation_id": str(generation_id),
                                "commit_sha": "a" * 40,
                            }
                        ],
                    },
                }
            }
            return httpx.Response(
                200, text=f"id: {run_id}:2\nevent: run.completed\ndata: {json.dumps(event)}\n\n"
            )
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        output = await demonstrate(
            client,
            "https://github.com/example/public",
            "Where is 42?",
            "test-token",
            timeout_seconds=5,
            poll_seconds=0,
        )
    assert "42" in output and "src/answer.py:1-2" in output
    assert len(requests) == 5


@pytest.mark.asyncio
async def test_demo_replays_incomplete_frame_and_reports_failure_code() -> None:
    repository_id, job_id, run_id = (uuid4() for _ in range(3))
    calls = 0

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield f"id: {run_id}:1\nevent: run.started\ndata: {{}}\n\n".encode()
            yield f"id: {run_id}:2\nevent: run.failed\n".encode()
            raise httpx.ReadError("disconnected")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/v1/repositories":
            return httpx.Response(
                202, json={"repository_id": str(repository_id), "job_id": str(job_id)}
            )
        if request.url.path == f"/v1/jobs/{job_id}":
            return httpx.Response(200, json={"status": "succeeded"})
        if request.url.path == "/v1/runs":
            return httpx.Response(202, json={"run_id": str(run_id)})
        if request.url.path == f"/v1/runs/{run_id}/events":
            calls += 1
            if calls == 1:
                assert "last-event-id" not in request.headers
                return httpx.Response(200, stream=BrokenStream())
            assert request.headers["last-event-id"] == f"{run_id}:1"
            return httpx.Response(
                200,
                text=f"id: {run_id}:2\nevent: run.failed\ndata: "
                '{"data":{"kind":"run.failed","code":"DEADLINE_EXCEEDED"}}\n\n',
            )
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        with pytest.raises(RuntimeError, match="Run failed: DEADLINE_EXCEEDED"):
            await demonstrate(
                client,
                "https://github.com/example/public",
                "Question",
                "test-token",
                timeout_seconds=5,
                poll_seconds=0,
            )
    assert calls == 2
