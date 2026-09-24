"""SSE stream keeps idle connections alive and releases leases on close."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from starlette.requests import ClientDisconnect

from contracts.models import Citation, CompletedData, RunResult
from reposcope.adapters.postgres_run_events import decode_db_run_event
from reposcope.application.run_stream import RunStream
from reposcope.ports.run_events import EventBatch
from reposcope.transport.http.app import _RunStreamingResponse


def test_persisted_completed_event_decodes_citation_uuids() -> None:
    run_id, repository_id, generation_id, chunk_id = (uuid4() for _ in range(4))
    citation = Citation(
        chunk_id=chunk_id,
        repository_id=repository_id,
        generation_id=generation_id,
        commit_sha="a" * 40,
        path="src/answer.py",
        start_line=1,
        end_line=2,
    )
    data = CompletedData(
        result=RunResult(
            answer="The answer is cited.",
            citations=[citation],
            evidence_status="supported",
            model="mock",
            estimated_cost_usd="0.000000",
        )
    )
    decoded = decode_db_run_event(run_id, 1, datetime.now(UTC), data.model_dump_json())
    assert isinstance(decoded.data, CompletedData)
    assert decoded.data.result.citations == [citation]


class EmptyStore:
    def __init__(self) -> None:
        self.released: list[UUID] = []

    async def open(self, principal_id: UUID, run_id: UUID, after: int) -> UUID:
        return uuid4()

    async def batch(
        self, connection_id: UUID, principal_id: UUID, run_id: UUID, after: int
    ) -> EventBatch:
        return EventBatch((), False)

    async def release(self, connection_id: UUID) -> None:
        self.released.append(connection_id)


@pytest.mark.asyncio
async def test_idle_heartbeat_and_disconnect_release() -> None:
    store = EmptyStore()
    principal, run = uuid4(), uuid4()
    stream = RunStream(store, heartbeat_seconds=0)
    connection_id, after = await stream.open(principal, run, None)
    iterator = stream.stream(connection_id, principal, run, after)
    assert await anext(iterator) == ": keep-alive\n\n"
    await iterator.aclose()
    assert store.released == [connection_id]


@pytest.mark.asyncio
async def test_send_failure_releases_slot_before_first_event() -> None:
    store = EmptyStore()
    principal, run, connection_id = uuid4(), uuid4(), uuid4()
    stream = RunStream(store).stream(connection_id, principal, run, 0)
    response = _RunStreamingResponse(stream, store, connection_id)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_: object) -> None:
        raise OSError("client disconnected")

    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "http_version": "1.1",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
    }
    with pytest.raises(ClientDisconnect):
        await response(scope, receive, send)
    assert store.released == [connection_id]
