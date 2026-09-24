"""T09 real PostgreSQL run timeline and authenticated replay acceptance."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from contracts.models import AgentRequested, Citation, RunResult
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.adapters.postgres_run_events import PostgresRunEvents, decode_db_run_event
from reposcope.domain.delivery import Complete, Lease
from reposcope.domain.errors import WorkError
from tests.integration.test_work_persistence import DatabaseHarness, database, ingest, ready

pytestmark = pytest.mark.integration
__all__ = ["database"]


@pytest.mark.asyncio
async def test_terminal_result_and_replay_event_commit_together(
    database: DatabaseHarness,
) -> None:
    accepted = await ingest(database)
    generation_id = await ready(database, accepted)
    response = await database.client.post(
        "/v1/runs",
        json={"repository_id": str(accepted.repository_id), "question": "Where is the answer?"},
        headers={"Idempotency-Key": "t09-terminal"},
    )
    assert response.status_code == 202
    run_id = UUID(response.json()["run_id"])
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s", (run_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    event = AgentRequested.model_validate_json(row[0])
    delivery = PostgresDeliveryRepository(database.pool)
    lease = await delivery.claim(event, "agent", uuid4())
    assert isinstance(lease, Lease)
    result = RunResult(
        answer="The answer is cited.",
        citations=[
            Citation(
                chunk_id=uuid4(),
                repository_id=accepted.repository_id,
                generation_id=generation_id,
                commit_sha="a" * 40,
                path="src/answer.py",
                start_line=1,
                end_line=2,
            )
        ],
        evidence_status="supported",
        model="mock",
        estimated_cost_usd="0.000000",
    )
    await delivery.finalize(lease, Complete(result))
    cursor = await database.owner.execute(
        "SELECT sequence,occurred_at,data::text FROM reposcope.run_events "
        "WHERE run_id=%s ORDER BY sequence",
        (run_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    sequence, occurred_at, data = cast(tuple[int, datetime, str], rows[0])
    replayed = decode_db_run_event(run_id, sequence, occurred_at, data)
    assert replayed.sequence == 1
    assert replayed.data.kind == "run.completed"
    assert replayed.data.result == result
    assert await delivery.completed("agent", event.event_id)
    stream = await database.client.get(f"/v1/runs/{run_id}/events")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert f"id: {run_id}:1\n" in stream.text
    assert "event: run.completed\n" in stream.text
    replay = await database.client.get(
        f"/v1/runs/{run_id}/events", headers={"Last-Event-ID": f"{run_id}:1"}
    )
    assert replay.status_code == 200 and replay.text == ""
    foreign = await database.client.get(
        f"/v1/runs/{run_id}/events", headers={"Last-Event-ID": f"{uuid4()}:1"}
    )
    assert foreign.status_code == 422
    future = await database.client.get(
        f"/v1/runs/{run_id}/events", headers={"Last-Event-ID": f"{run_id}:2"}
    )
    assert future.status_code == 422
    absent = await database.client.get(f"/v1/runs/{uuid4()}/events")
    assert absent.status_code == 404
    unauthenticated = await database.client.get(
        f"/v1/runs/{run_id}/events", headers={"Authorization": ""}
    )
    assert unauthenticated.status_code == 401
    await database.owner.execute(
        "UPDATE reposcope.agent_runs SET created_at=clock_timestamp()-interval '26 hours',"
        "updated_at=clock_timestamp()-interval '25 hours' WHERE run_id=%s",
        (run_id,),
    )
    assert await PostgresRunEvents(database.pool).prune() == 1
    cursor = await database.owner.execute(
        "SELECT count(*) FROM reposcope.run_events WHERE run_id=%s", (run_id,)
    )
    row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 0


@pytest.mark.asyncio
async def test_connection_caps_and_terminal_retention(database: DatabaseHarness) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    response = await database.client.post(
        "/v1/runs",
        json={"repository_id": str(accepted.repository_id), "question": "answer?"},
        headers={"Idempotency-Key": "t09-limits"},
    )
    assert response.status_code == 202
    run_id = UUID(response.json()["run_id"])
    store = PostgresRunEvents(database.pool)
    principal = database.settings.principal_id
    first = await store.open(principal, run_id, 0)
    second = await store.open(principal, run_id, 0)
    with pytest.raises(WorkError) as capped:
        await store.open(principal, run_id, 0)
    assert capped.value.code == "RATE_LIMITED"
    await store.release(first)
    third = await store.open(principal, run_id, 0)
    await store.release(second)
    await store.release(third)
    await database.owner.execute(
        "UPDATE reposcope.agent_runs SET status='failed',failure_code='DEADLINE_EXCEEDED',"
        "created_at=clock_timestamp()-interval '26 hours',"
        "updated_at=clock_timestamp()-interval '25 hours' WHERE run_id=%s",
        (run_id,),
    )
    expired = await database.client.get(f"/v1/runs/{run_id}/events")
    assert expired.status_code == 410
