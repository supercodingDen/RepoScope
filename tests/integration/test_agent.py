"""A queued run executes against its admitted ready revision with no paid calls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from json import loads
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from contracts.models import AgentRequested
from reposcope.adapters.embedding import MockEmbeddingProvider
from reposcope.adapters.postgres_agent import PostgresAgentRepository
from reposcope.adapters.postgres_index import PostgresIndexRepository
from reposcope.adapters.postgres_retrieval import PostgresRetrievalRepository
from reposcope.application.agent import AgentHandler, ModelTurn
from reposcope.application.index import IndexHandler
from reposcope.application.retrieval import RetrievalService
from reposcope.domain.delivery import Complete, Lease, PermanentFailure, Staged
from reposcope.domain.errors import WorkError
from tests.integration.test_index import staged_files
from tests.integration.test_work_persistence import DatabaseHarness, database

pytestmark = pytest.mark.integration
__all__ = ["database"]


@pytest.mark.asyncio
async def test_one_hop_chunks_use_only_pinned_manifest_imports(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, source_event = await staged_files(
        database,
        tmp_path,
        {
            "src/main.ts": b"import { answer } from './answer'\nimport 'external'\n",
            "src/answer.ts": b"export const answer = 42\n",
            "src/unused.ts": b"export const unused = 1\n",
        },
    )
    source_lease = await delivery.claim(source_event, "source", uuid4())
    assert isinstance(source_lease, Lease)
    assert isinstance(
        await IndexHandler(
            PostgresIndexRepository(delivery), store, MockEmbeddingProvider()
        ).handle(source_lease),
        Staged,
    )
    accepted = await database.client.post(
        "/v1/runs",
        headers={"Idempotency-Key": "one-hop"},
        json={"repository_id": str(source_event.payload.repository_id), "question": "answer?"},
    )
    assert accepted.status_code == 202
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s",
        (UUID(accepted.json()["run_id"]),),
    )
    row = await cursor.fetchone()
    assert row is not None
    event = AgentRequested.model_validate_json(row[0])
    lease = await delivery.claim(event, "agent", uuid4())
    assert isinstance(lease, Lease)
    repository = PostgresAgentRepository(delivery)
    preparation = await repository.prepare(lease)
    chunks = await repository.one_hop_chunks(lease, preparation, ("src/main.ts",))
    assert [chunk.path for chunk in chunks] == ["src/answer.ts"]
    assert all(chunk.generation_id == source_event.payload.generation_id for chunk in chunks)


@pytest.mark.asyncio
async def test_mock_agent_completes_pinned_run_and_preserves_citation(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, source_event = await staged_files(
        database, tmp_path, {"src/answer.py": b"def answer():\n    return 42\n"}
    )
    source_lease = await delivery.claim(source_event, "source", uuid4())
    assert isinstance(source_lease, Lease)
    assert isinstance(
        await IndexHandler(
            PostgresIndexRepository(delivery), store, MockEmbeddingProvider()
        ).handle(source_lease),
        Staged,
    )
    accepted = await database.client.post(
        "/v1/runs",
        headers={"Idempotency-Key": "agent-mock"},
        json={
            "repository_id": str(source_event.payload.repository_id),
            "question": "Where is answer defined?",
        },
    )
    assert accepted.status_code == 202
    run_id = UUID(accepted.json()["run_id"])
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s", (run_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    event = AgentRequested.model_validate_json(row[0])
    lease = await delivery.claim(event, "agent", uuid4())
    assert isinstance(lease, Lease)
    outcome = await AgentHandler(
        PostgresAgentRepository(delivery),
        RetrievalService(PostgresRetrievalRepository(database.pool), MockEmbeddingProvider()),
        store,
        None,
    ).handle(lease)
    assert isinstance(outcome, Complete)
    assert outcome.result is not None
    assert outcome.result.citations[0].path == "src/answer.py"
    assert outcome.result.citations[0].generation_id == source_event.payload.generation_id
    assert outcome.result.estimated_cost_usd == "0.000000"
    await delivery.finalize(lease, outcome)
    cursor = await database.owner.execute(
        "SELECT sequence,kind FROM reposcope.run_events WHERE run_id=%s ORDER BY sequence",
        (run_id,),
    )
    assert [(int(sequence), kind) for sequence, kind in await cursor.fetchall()] == [
        (1, "run.started"),
        (2, "tool.started"),
        (3, "tool.completed"),
        (4, "run.completed"),
    ]
    result = await database.client.get(f"/v1/runs/{run_id}")
    assert result.status_code == 200
    assert result.json()["status"] == "succeeded"
    cursor = await database.owner.execute("SELECT count(*) FROM reposcope.model_attempts")
    attempts_row = await cursor.fetchone()
    assert attempts_row is not None and int(attempts_row[0]) == 0


@pytest.mark.asyncio
async def test_model_budget_reservation_is_fenced_and_keeps_uncertain_cost(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, source_event = await staged_files(
        database, tmp_path, {"a.py": b"answer = 42\n"}
    )
    source_lease = await delivery.claim(source_event, "source", uuid4())
    assert isinstance(source_lease, Lease)
    assert isinstance(
        await IndexHandler(
            PostgresIndexRepository(delivery), store, MockEmbeddingProvider()
        ).handle(source_lease),
        Staged,
    )
    accepted = await database.client.post(
        "/v1/runs",
        headers={"Idempotency-Key": "agent-budget"},
        json={"repository_id": str(source_event.payload.repository_id), "question": "answer?"},
    )
    assert accepted.status_code == 202
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s",
        (UUID(accepted.json()["run_id"]),),
    )
    row = await cursor.fetchone()
    assert row is not None
    event = AgentRequested.model_validate_json(row[0])
    lease = await delivery.claim(event, "agent", uuid4())
    assert isinstance(lease, Lease)
    repository = PostgresAgentRepository(delivery)
    today = datetime.now(UTC).date()
    with pytest.raises(WorkError) as stale:
        await repository.reserve_model_attempt(
            lease, 2000, Decimal("0.20"), Decimal("1.20"), today - timedelta(days=8)
        )
    assert stale.value.code == "PROVIDER_UNAVAILABLE"
    with pytest.raises(WorkError) as oversized:
        await repository.reserve_model_attempt(
            lease, 24001, Decimal("0.20"), Decimal("1.20"), today
        )
    assert oversized.value.code == "VALIDATION_ERROR"
    attempt, reserved = await repository.reserve_model_attempt(
        lease, 2000, Decimal("0.20"), Decimal("1.20"), today
    )
    assert attempt == 1 and reserved > 0
    await repository.settle_model_attempt(lease, attempt, None, None)
    cursor = await database.owner.execute(
        "SELECT state,reserved_usd::text FROM reposcope.model_attempts WHERE run_id=%s",
        (event.payload.run_id,),
    )
    row = await cursor.fetchone()
    assert row is not None and row[0] == "uncertain" and Decimal(row[1]) == reserved
    concurrent = await asyncio.gather(
        *(
            repository.reserve_model_attempt(lease, 2000, Decimal("0.20"), Decimal("1.20"), today)
            for _ in range(2)
        )
    )
    assert {item[0] for item in concurrent} == {2, 3}
    for expected in range(4, 7):
        attempt, _ = await repository.reserve_model_attempt(
            lease, 2000, Decimal("0.20"), Decimal("1.20"), today
        )
        assert attempt == expected
    with pytest.raises(WorkError) as exhausted:
        await repository.reserve_model_attempt(lease, 2000, Decimal("0.20"), Decimal("1.20"), today)
    assert exhausted.value.code == "BUDGET_EXCEEDED"
    cumulative = await repository.reserved_cost(lease)
    assert cumulative > reserved
    await delivery.release(lease, 0)
    redelivery = await delivery.claim(event, "agent", uuid4())
    assert isinstance(redelivery, Lease)
    assert await repository.reserved_cost(redelivery) == cumulative
    for expected in range(1, 7):
        assert await repository.record_tool_step(redelivery) == expected
    with pytest.raises(ValueError, match="Tool step limit"):
        await repository.record_tool_step(redelivery)


@pytest.mark.asyncio
async def test_luna_path_reserves_before_fake_provider_and_settles_usage(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, source_event = await staged_files(
        database, tmp_path, {"answer.py": b"def answer():\n    return 42\n"}
    )
    source_lease = await delivery.claim(source_event, "source", uuid4())
    assert isinstance(source_lease, Lease)
    assert isinstance(
        await IndexHandler(
            PostgresIndexRepository(delivery), store, MockEmbeddingProvider()
        ).handle(source_lease),
        Staged,
    )
    accepted = await database.client.post(
        "/v1/runs",
        headers={"Idempotency-Key": "agent-live-fake"},
        json={"repository_id": str(source_event.payload.repository_id), "question": "answer?"},
    )
    assert accepted.status_code == 202
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s",
        (UUID(accepted.json()["run_id"]),),
    )
    row = await cursor.fetchone()
    assert row is not None
    event = AgentRequested.model_validate_json(row[0])
    lease = await delivery.claim(event, "agent", uuid4())
    assert isinstance(lease, Lease)

    class FakeLuna:
        model = "gpt-5.6-luna"

        async def respond(self, history: list[dict[str, object]]) -> ModelTurn:
            cursor = await database.owner.execute(
                "SELECT state FROM reposcope.model_attempts WHERE run_id=%s",
                (event.payload.run_id,),
            )
            assert await cursor.fetchone() == ("reserved",)
            evidence = loads(str(history[2]["content"]))
            chunk_id = UUID(evidence["results"][0]["chunk_id"])
            return ModelTurn((), "answer is in answer.py", (chunk_id,), 700, 100)

    outcome = await AgentHandler(
        PostgresAgentRepository(delivery),
        RetrievalService(PostgresRetrievalRepository(database.pool), MockEmbeddingProvider()),
        store,
        FakeLuna(),
        Decimal("0.20"),
        Decimal("1.20"),
        datetime.now(UTC).date(),
    ).handle(lease)
    assert isinstance(outcome, Complete)
    assert outcome.result is not None
    assert outcome.result.model == "gpt-5.6-luna"
    assert outcome.result.citations[0].path == "answer.py"
    assert Decimal(outcome.result.estimated_cost_usd) > 0
    cursor = await database.owner.execute(
        "SELECT state,actual_input_tokens,actual_output_tokens FROM reposcope.model_attempts "
        "WHERE run_id=%s",
        (event.payload.run_id,),
    )
    settled = await cursor.fetchone()
    assert settled is not None
    assert settled[0] == "settled" and int(settled[1]) == 700 and int(settled[2]) == 100


@pytest.mark.asyncio
async def test_provider_outage_keeps_reserved_cost_and_commits_safe_failure(
    database: DatabaseHarness, tmp_path: Path
) -> None:
    delivery, store, source_event = await staged_files(
        database, tmp_path, {"answer.py": b"answer = 42\n"}
    )
    source_lease = await delivery.claim(source_event, "source", uuid4())
    assert isinstance(source_lease, Lease)
    assert isinstance(
        await IndexHandler(
            PostgresIndexRepository(delivery), store, MockEmbeddingProvider()
        ).handle(source_lease),
        Staged,
    )
    accepted = await database.client.post(
        "/v1/runs",
        headers={"Idempotency-Key": "agent-provider-outage"},
        json={"repository_id": str(source_event.payload.repository_id), "question": "answer?"},
    )
    assert accepted.status_code == 202
    run_id = UUID(accepted.json()["run_id"])
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s", (run_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    event = AgentRequested.model_validate_json(row[0])
    lease = await delivery.claim(event, "agent", uuid4())
    assert isinstance(lease, Lease)

    class BrokenProvider:
        model = "gpt-5.6-luna"

        async def respond(self, history: list[dict[str, object]]) -> ModelTurn:
            raise ConnectionError("provider key must never be logged")

    outcome = await AgentHandler(
        PostgresAgentRepository(delivery),
        RetrievalService(PostgresRetrievalRepository(database.pool), MockEmbeddingProvider()),
        store,
        BrokenProvider(),
        Decimal("0.20"),
        Decimal("1.20"),
        datetime.now(UTC).date(),
    ).handle(lease)
    assert outcome == PermanentFailure("PROVIDER_UNAVAILABLE")
    await delivery.finalize(lease, outcome)
    cursor = await database.owner.execute(
        "SELECT state,reserved_usd::text FROM reposcope.model_attempts WHERE run_id=%s", (run_id,)
    )
    attempt = await cursor.fetchone()
    assert attempt is not None and attempt[0] == "uncertain" and Decimal(attempt[1]) > 0
    response = await database.client.get(f"/v1/runs/{run_id}")
    assert response.status_code == 200 and response.json()["failure_code"] == "PROVIDER_UNAVAILABLE"
    assert "provider key" not in response.text
    cursor = await database.owner.execute(
        "SELECT kind FROM reposcope.run_events WHERE run_id=%s ORDER BY sequence DESC LIMIT 1",
        (run_id,),
    )
    assert await cursor.fetchone() == ("run.failed",)
