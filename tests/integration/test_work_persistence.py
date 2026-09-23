"""Real PostgreSQL HTTP transactions, concurrency and rollback acceptance."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from psycopg import AsyncConnection, sql
from psycopg.errors import CheckViolation, ForeignKeyViolation
from psycopg_pool import AsyncConnectionPool

from contracts.models import (
    AgentRequested,
    JobView,
    RepositoryAccepted,
    RunAccepted,
    RunCreate,
    RunView,
)
from reposcope.adapters.postgres_run_events import PostgresRunEvents
from reposcope.adapters.postgres_work import PostgresWorkRepository
from reposcope.application.work import AdmissionPolicy, WorkService
from reposcope.infrastructure.db.migrate import run_migrations
from reposcope.runtime import RuntimeResources
from reposcope.settings import RuntimeSettings
from reposcope.transport.http.app import create_public_application
from tests.integration.test_migrations import _integration_configuration

pytestmark = pytest.mark.integration


class ReadyProbe:
    async def database_migrated(self, version: str) -> bool:
        return True

    async def redis_available(self) -> bool:
        return True

    async def jetstream_available(self) -> bool:
        return True

    async def close(self) -> None:
        pass


@dataclass
class DatabaseHarness:
    client: httpx.AsyncClient
    owner: AsyncConnection[tuple[str, ...]]
    pool: AsyncConnectionPool[AsyncConnection[tuple[str]]]
    principal: UUID
    settings: RuntimeSettings


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseHarness]:
    config, runtime_url = _integration_configuration()
    await run_migrations(config)
    owner = await AsyncConnection[tuple[str, ...]].connect(config.database_url, autocommit=True)
    pool: AsyncConnectionPool[AsyncConnection[tuple[str]]] = AsyncConnectionPool(
        runtime_url, min_size=1, max_size=10, open=False
    )
    await pool.open(wait=True)
    await owner.execute("TRUNCATE reposcope.repositories CASCADE")
    principal = uuid4()
    settings = RuntimeSettings.from_values(
        {
            "DATABASE_URL": runtime_url,
            "REDIS_URL": "redis://localhost:6379/0",
            "NATS_URL": "nats://localhost:4222",
            "REPOSCOPE_API_TOKEN": "synthetic-test-token",
            "REPOSCOPE_PRINCIPAL_ID": str(principal),
        }
    )
    app = create_public_application(
        RuntimeResources(ReadyProbe(), 0.1),
        settings,
        WorkService(PostgresWorkRepository(pool)),
        events=PostgresRunEvents(pool),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"Authorization": "Bearer synthetic-test-token"},
        ) as client:
            yield DatabaseHarness(client, owner, pool, principal, settings)
    finally:
        await pool.close()
        await owner.execute("TRUNCATE reposcope.repositories CASCADE")
        await owner.close()


@pytest.mark.asyncio
async def test_hundred_concurrent_http_retries_commit_one_ingestion(
    database: DatabaseHarness,
) -> None:
    responses = await asyncio.gather(
        *(
            database.client.post(
                "/v1/repositories",
                headers={"Idempotency-Key": "same"},
                json={"url": "https://github.com/example/repo"},
            )
            for _ in range(100)
        )
    )
    assert {response.status_code for response in responses} == {202}
    accepted = RepositoryAccepted.model_validate_json(responses[0].content)
    assert all(response.content == responses[0].content for response in responses)
    for table in (
        "repositories",
        "jobs",
        "index_generations",
        "idempotency_requests",
        "outbox_events",
    ):
        cursor = await database.owner.execute(
            sql.SQL("SELECT count(*)::text FROM reposcope.{}").format(sql.Identifier(table))
        )
        assert await cursor.fetchone() == ("1",)
    get = await database.client.get(f"/v1/jobs/{accepted.job_id}")
    assert get.status_code == 200


def another_client(
    database: DatabaseHarness,
    *,
    principal: UUID | None = None,
    policy: AdmissionPolicy | None = None,
) -> httpx.AsyncClient:
    app = create_public_application(
        RuntimeResources(ReadyProbe(), 0.1),
        replace(database.settings, principal_id=principal or database.principal),
        WorkService(PostgresWorkRepository(database.pool), policy),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": "Bearer synthetic-test-token"},
    )


async def ingest(database: DatabaseHarness, key: str = "ingest") -> RepositoryAccepted:
    response = await database.client.post(
        "/v1/repositories",
        headers={"Idempotency-Key": key},
        json={"url": "https://github.com/example/repo"},
    )
    assert response.status_code == 202
    return RepositoryAccepted.model_validate_json(response.content)


async def ready(
    database: DatabaseHarness, accepted: RepositoryAccepted, sha: str = "a" * 40
) -> UUID:
    await database.owner.execute(
        "INSERT INTO reposcope.source_revisions VALUES (%s,%s,%s,now()) ON CONFLICT DO NOTHING",
        (accepted.repository_id, database.principal, sha),
    )
    await database.owner.execute(
        "UPDATE reposcope.index_generations SET status='ready',commit_sha=%s "
        "WHERE generation_id=(SELECT generation_id FROM reposcope.jobs WHERE job_id=%s)",
        (sha, accepted.job_id),
    )
    await database.owner.execute(
        "UPDATE reposcope.jobs SET status='succeeded', progress_percent=100,commit_sha=%s "
        "WHERE job_id=%s",
        (sha, accepted.job_id),
    )
    cursor = await database.owner.execute(
        "UPDATE reposcope.repositories SET active_generation_id=latest_requested_generation_id "
        "WHERE repository_id=%s RETURNING active_generation_id::text",
        (accepted.repository_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    return UUID(row[0])


async def count(database: DatabaseHarness, table: str) -> int:
    cursor = await database.owner.execute(
        sql.SQL("SELECT count(*)::text FROM reposcope.{}").format(sql.Identifier(table))
    )
    row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_hundred_duplicate_runs_pin_snapshot_and_replay_before_new_generation(
    database: DatabaseHarness,
) -> None:
    accepted = await ingest(database)
    payload = {"repository_id": str(accepted.repository_id), "question": "private question"}
    not_ready = await database.client.post(
        "/v1/runs", json=payload, headers={"Idempotency-Key": "run"}
    )
    assert not_ready.status_code == 409 and "INDEX_NOT_READY" in not_ready.text
    generation_id = await ready(database, accepted)
    responses = await asyncio.gather(
        *(
            database.client.post("/v1/runs", json=payload, headers={"Idempotency-Key": "ingest"})
            for _ in range(100)
        )
    )
    assert {response.status_code for response in responses} == {202}
    assert all(response.content == responses[0].content for response in responses)
    run = RunAccepted.model_validate_json(responses[0].content)
    assert run.generation_id == generation_id
    assert await count(database, "agent_runs") == 1
    assert await count(database, "usage_reservations") == 1
    assert await count(database, "outbox_events") == 2
    assert await count(database, "idempotency_requests") == 2
    cursor = await database.owner.execute(
        "SELECT payload::text FROM reposcope.outbox_events WHERE run_id=%s",
        (run.run_id,),
    )
    row = await cursor.fetchone()
    assert row is not None and "private question" not in row[0]
    event = AgentRequested.model_validate_json(row[0])
    assert event.payload.commit_sha == "a" * 40
    assert event.payload.generation_id == generation_id
    assert event.payload.policy_version == "routing-v1"
    second_generation = await ready(database, await ingest(database, "next"), "b" * 40)
    assert second_generation != generation_id
    replay = await database.client.post(
        "/v1/runs", json=payload, headers={"Idempotency-Key": "ingest"}
    )
    assert replay.content == responses[0].content
    persisted = RunView.model_validate_json(
        (await database.client.get(f"/v1/runs/{run.run_id}")).content
    )
    assert persisted.generation_id == generation_id
    async with another_client(database, principal=uuid4()) as stranger:
        assert (await stranger.get(f"/v1/runs/{run.run_id}")).status_code == 404
        assert (await stranger.get(f"/v1/jobs/{accepted.job_id}")).status_code == 404
        assert (
            await stranger.post("/v1/runs", json=payload, headers={"Idempotency-Key": "other"})
        ).status_code == 404


@pytest.mark.asyncio
async def test_semantic_identity_scope_conflicts_and_retention(database: DatabaseHarness) -> None:
    accepted = await ingest(database)
    response = await database.client.post(
        "/v1/repositories",
        headers={"Idempotency-Key": "ingest"},
        content=b' {"requested_ref":"HEAD", "url": "https://github.com/example/repo"} ',
    )
    assert RepositoryAccepted.model_validate_json(response.content) == accepted
    await database.owner.execute(
        "UPDATE reposcope.idempotency_requests SET created_at=created_at-interval '8 days', "
        "expires_at=expires_at-interval '8 days'",
    )
    assert await ingest(database) == accepted
    contenders = await asyncio.gather(
        *(
            database.client.post(
                "/v1/repositories",
                headers={"Idempotency-Key": "race"},
                json={"url": "https://github.com/example/repo", "requested_ref": f"branch-{index}"},
            )
            for index in range(20)
        )
    )
    assert [response.status_code for response in contenders].count(202) == 1
    assert [response.status_code for response in contenders].count(409) == 19
    next_work = await ingest(database, "distinct")
    assert next_work.repository_id == accepted.repository_id and next_work.job_id != accepted.job_id
    async with another_client(database, principal=uuid4()) as stranger:
        response = await stranger.post(
            "/v1/repositories",
            headers={"Idempotency-Key": "ingest"},
            json={"url": "https://github.com/example/repo"},
        )
        other = RepositoryAccepted.model_validate_json(response.content)
        assert other.repository_id != accepted.repository_id


@pytest.mark.asyncio
@pytest.mark.parametrize("run", [False, True])
async def test_outbox_failure_rolls_back_every_submission_row(
    database: DatabaseHarness, run: bool
) -> None:
    payload: dict[str, str] = {"url": "https://github.com/example/repo"}
    route = "/v1/repositories"
    baseline = 0
    if run:
        accepted = await ingest(database)
        await ready(database, accepted)
        payload = {"repository_id": str(accepted.repository_id), "question": "rollback"}
        route = "/v1/runs"
        baseline = 1
    await database.owner.execute(
        "CREATE FUNCTION reposcope.reject_test_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'forced test failure' USING ERRCODE='23514'; END $$",
    )
    await database.owner.execute(
        "CREATE TRIGGER reject_test_outbox BEFORE INSERT ON reposcope.outbox_events "
        "FOR EACH ROW EXECUTE FUNCTION reposcope.reject_test_outbox()",
    )
    try:
        response = await database.client.post(
            route, json=payload, headers={"Idempotency-Key": "rollback"}
        )
        assert response.status_code == 500
        assert "forced test failure" not in response.text
        for table in (
            "repositories",
            "jobs",
            "index_generations",
            "idempotency_requests",
            "outbox_events",
        ):
            assert await count(database, table) == baseline
        for table in ("agent_runs", "usage_reservations"):
            assert await count(database, table) == 0
    finally:
        await database.owner.execute("DROP TRIGGER reject_test_outbox ON reposcope.outbox_events")
        await database.owner.execute("DROP FUNCTION reposcope.reject_test_outbox()")


@pytest.mark.asyncio
async def test_shared_capacity_and_budget_races(database: DatabaseHarness) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    payload = {"repository_id": str(accepted.repository_id), "question": "budget"}
    policy = AdmissionPolicy(
        reservation_usd=Decimal("0.100000"), daily_limit_usd=Decimal("0.200000")
    )
    async with another_client(database, policy=policy) as http:
        responses = await asyncio.gather(
            *(
                http.post("/v1/runs", json=payload, headers={"Idempotency-Key": f"budget-{index}"})
                for index in range(20)
            )
        )
        assert [response.status_code for response in responses].count(202) == 2
        assert [response.status_code for response in responses].count(429) == 18
        for index, response in enumerate(responses):
            if response.status_code == 202:
                replay = await http.post(
                    "/v1/runs", json=payload, headers={"Idempotency-Key": f"budget-{index}"}
                )
                assert replay.content == response.content
    assert await count(database, "usage_reservations") == 2
    cursor = await database.owner.execute(
        "SELECT sum(amount_usd)::text FROM reposcope.usage_reservations"
    )
    assert await cursor.fetchone() == ("0.200000",)
    async with another_client(database, policy=AdmissionPolicy(pending_limit=3)) as http:
        responses = await asyncio.gather(
            *(
                http.post(
                    "/v1/repositories",
                    json={"url": "https://github.com/example/repo"},
                    headers={"Idempotency-Key": f"capacity-{index}"},
                )
                for index in range(10)
            )
        )
        assert [response.status_code for response in responses].count(202) == 1
        assert [response.status_code for response in responses].count(429) == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["reserved", "settled", "uncertain", "released"])
async def test_conservative_reservation_states_and_project_window(
    database: DatabaseHarness, state: str
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    payload = {"repository_id": str(accepted.repository_id), "question": "budget"}
    policy = AdmissionPolicy(
        reservation_usd=Decimal("0.100000"), project_limit_usd=Decimal("0.100000")
    )
    async with another_client(database, policy=policy) as http:
        assert (
            await http.post("/v1/runs", json=payload, headers={"Idempotency-Key": "first"})
        ).status_code == 202
        await database.owner.execute(
            "UPDATE reposcope.usage_reservations SET state=%s,budget_day=budget_day-1",
            (state,),
        )
        response = await http.post("/v1/runs", json=payload, headers={"Idempotency-Key": "second"})
        assert response.status_code == (202 if state == "released" else 429)


@pytest.mark.asyncio
async def test_database_scope_status_and_pinned_revision_constraints(
    database: DatabaseHarness,
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    await database.owner.execute(
        "INSERT INTO reposcope.source_revisions VALUES (%s,%s,%s,now())",
        (accepted.repository_id, database.principal, "b" * 40),
    )
    with pytest.raises(ForeignKeyViolation):
        await database.owner.execute(
            "UPDATE reposcope.jobs SET commit_sha=%s WHERE job_id=%s", ("b" * 40, accepted.job_id)
        )
    with pytest.raises(ForeignKeyViolation):
        await database.owner.execute(
            "UPDATE reposcope.jobs SET principal_id=%s WHERE job_id=%s", (uuid4(), accepted.job_id)
        )
    with pytest.raises(CheckViolation):
        await database.owner.execute(
            "UPDATE reposcope.jobs SET status='failed' WHERE job_id=%s", (accepted.job_id,)
        )
    view = JobView.model_validate_json(
        (await database.client.get(f"/v1/jobs/{accepted.job_id}")).content
    )
    assert view.commit_sha == "a" * 40


@pytest.mark.asyncio
async def test_closed_database_pool_is_safe_unavailable(database: DatabaseHarness) -> None:
    await database.pool.close()
    response = await database.client.post(
        "/v1/repositories",
        json={"url": "https://github.com/a/b"},
        headers={"Idempotency-Key": "outage"},
    )
    assert response.status_code == 503
    assert "postgresql" not in response.text


@pytest.mark.asyncio
async def test_cancelled_database_wait_does_not_leave_work(database: DatabaseHarness) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    service = WorkService(PostgresWorkRepository(database.pool))
    async with database.owner.transaction():
        await database.owner.execute("SELECT singleton FROM reposcope.admission_lock FOR UPDATE")
        task = asyncio.create_task(
            service.create_run(
                RunCreate(repository_id=accepted.repository_id, question="cancelled"),
                database.principal,
                "cancelled",
                uuid4(),
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await count(database, "agent_runs") == 0
    assert await count(database, "usage_reservations") == 0


@pytest.mark.asyncio
async def test_database_result_contract_corruption_maps_to_safe_internal_error(
    database: DatabaseHarness,
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    response = await database.client.post(
        "/v1/runs",
        json={"repository_id": str(accepted.repository_id), "question": "private question"},
        headers={"Idempotency-Key": "result"},
    )
    run = RunAccepted.model_validate_json(response.content)
    await database.owner.execute(
        "UPDATE reposcope.agent_runs SET status='succeeded',result=%s::jsonb WHERE run_id=%s",
        ('{"unsafe":"private question"}', run.run_id),
    )
    response = await database.client.get(f"/v1/runs/{run.run_id}")
    assert response.status_code == 500
    assert "private question" not in response.text


@pytest.mark.asyncio
async def test_project_budget_is_shared_across_server_principals(database: DatabaseHarness) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    policy = AdmissionPolicy(
        reservation_usd=Decimal("0.100000"), project_limit_usd=Decimal("0.100000")
    )
    async with another_client(database, policy=policy) as first:
        response = await first.post(
            "/v1/runs",
            json={"repository_id": str(accepted.repository_id), "question": "first"},
            headers={"Idempotency-Key": "shared"},
        )
        assert response.status_code == 202
    other_principal = uuid4()
    async with another_client(database, principal=other_principal, policy=policy) as other:
        other_database = replace(database, client=other, principal=other_principal)
        other_accepted = await ingest(other_database)
        await ready(other_database, other_accepted)
        response = await other.post(
            "/v1/runs",
            json={"repository_id": str(other_accepted.repository_id), "question": "other"},
            headers={"Idempotency-Key": "shared"},
        )
        assert response.status_code == 429
        assert "BUDGET_EXCEEDED" in response.text


@pytest.mark.asyncio
async def test_changed_question_race_has_one_run_reservation_and_event(
    database: DatabaseHarness,
) -> None:
    accepted = await ingest(database)
    await ready(database, accepted)
    responses = await asyncio.gather(
        *(
            database.client.post(
                "/v1/runs",
                json={
                    "repository_id": str(accepted.repository_id),
                    "question": f"question-{index}",
                },
                headers={"Idempotency-Key": "question-race"},
            )
            for index in range(20)
        )
    )
    assert [response.status_code for response in responses].count(202) == 1
    assert [response.status_code for response in responses].count(409) == 19
    assert await count(database, "agent_runs") == 1
    assert await count(database, "usage_reservations") == 1
    assert await count(database, "outbox_events") == 2
