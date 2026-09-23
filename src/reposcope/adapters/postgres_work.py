"""PostgreSQL atomic admission, durable work, replay and outbox persistence."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
from psycopg import AsyncConnection, sql
from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout
from pydantic import BaseModel, ValidationError

from contracts.models import (
    AgentPayload,
    AgentRequested,
    CommitSHA,
    Contract,
    IngestPayload,
    IngestRequested,
    JobView,
    RepositoryAccepted,
    RepositoryCreate,
    RunAccepted,
    RunCreate,
    RunView,
)
from reposcope.application.work import AdmissionPolicy, Submission
from reposcope.domain.errors import WorkError


@dataclass
class JsonRow:
    """One textual JSON database boundary, subsequently contract validated."""

    data: str


class Replay(Contract):
    fingerprint: str
    response_json: str


class RepositoryIdentity(Contract):
    repository_id: UUID


class Snapshot(Contract):
    generation_id: UUID | None
    commit_sha: CommitSHA | None
    status: str | None


class AdmissionFacts(Contract):
    pending: int
    daily: Decimal
    project: Decimal


async def _read[T: BaseModel](
    connection: AsyncConnection[tuple[str]],
    statement: str | sql.SQL | sql.Composed,
    parameters: Sequence[object],
    model: type[T],
) -> T | None:
    async with connection.cursor(row_factory=class_row(JsonRow)) as cursor:
        await cursor.execute(statement, parameters)
        row = await cursor.fetchone()
    if row is None:
        return None
    return model.model_validate_json(row.data)


class PostgresWorkRepository:
    """Use the existing bounded process pool and short, cancellable transactions."""

    def __init__(
        self,
        pool: AsyncConnectionPool[AsyncConnection[tuple[str]]],
        operation_timeout_seconds: float = 10.0,
    ) -> None:
        self.pool = pool
        self.operation_timeout_seconds = operation_timeout_seconds

    @asynccontextmanager
    async def _transaction(
        self, *, admission: bool = False
    ) -> AsyncIterator[AsyncConnection[tuple[str]]]:
        try:
            async with asyncio.timeout(self.operation_timeout_seconds):
                async with self.pool.connection(
                    timeout=self.operation_timeout_seconds
                ) as connection:
                    async with connection.transaction():
                        await connection.execute("SET LOCAL statement_timeout = '5s'")
                        await connection.execute("SET LOCAL lock_timeout = '5s'")
                        if admission:
                            cursor = await connection.execute(
                                "SELECT singleton::text FROM reposcope.admission_lock "
                                "WHERE singleton = true FOR UPDATE"
                            )
                            if await cursor.fetchone() is None:
                                raise WorkError("INTERNAL_ERROR")
                        yield connection
        except (TimeoutError, PoolTimeout, psycopg.OperationalError) as error:
            raise WorkError("DEPENDENCY_UNAVAILABLE") from error
        except ValidationError as error:
            raise WorkError("INTERNAL_ERROR") from error

    async def _replay[T: Contract](
        self,
        connection: AsyncConnection[tuple[str]],
        submission: Submission,
        route: str,
        model: type[T],
    ) -> T | None:
        replay = await _read(
            connection,
            "SELECT json_build_object('fingerprint', fingerprint, "
            "'response_json', response::text)::text AS data "
            "FROM reposcope.idempotency_requests "
            "WHERE principal_id = %s AND route = %s AND idempotency_key = %s",
            (submission.principal_id, route, submission.key),
            Replay,
        )
        if replay is None:
            return None
        if replay.fingerprint != submission.fingerprint:
            raise WorkError("IDEMPOTENCY_CONFLICT")
        return model.model_validate_json(replay.response_json)

    async def _admit(
        self,
        connection: AsyncConnection[tuple[str]],
        submission: Submission,
        policy: AdmissionPolicy,
        *,
        run: bool,
    ) -> None:
        facts = await _read(
            connection,
            "SELECT json_build_object('pending', "
            "(SELECT count(*) FROM reposcope.jobs WHERE status IN ('queued','running')) + "
            "(SELECT count(*) FROM reposcope.agent_runs WHERE status IN ('queued','running')), "
            "'daily', coalesce(sum(amount_usd) FILTER (WHERE budget_day = %s), 0)::text, "
            "'project', coalesce(sum(amount_usd), 0)::text)::text AS data "
            "FROM reposcope.usage_reservations WHERE state <> 'released'",
            (submission.now.date(),),
            AdmissionFacts,
        )
        if facts is None:
            raise WorkError("INTERNAL_ERROR")
        policy.check(facts.pending, facts.daily, facts.project, run=run)

    async def _record(
        self,
        connection: AsyncConnection[tuple[str]],
        submission: Submission,
        response: RepositoryAccepted | RunAccepted,
        event: IngestRequested | AgentRequested,
    ) -> None:
        job_id = response.job_id if isinstance(response, RepositoryAccepted) else None
        run_id = response.run_id if isinstance(response, RunAccepted) else None
        route = "/v1/repositories" if job_id is not None else "/v1/runs"
        await connection.execute(
            "INSERT INTO reposcope.outbox_events "
            "(event_id, principal_id, aggregate_id, event_type, payload, "
            "occurred_at, trace_id, job_id, run_id) "
            "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
            (
                event.event_id,
                submission.principal_id,
                event.aggregate_id,
                event.event_type,
                event.model_dump_json(),
                event.occurred_at,
                event.trace_id,
                job_id,
                run_id,
            ),
        )
        await connection.execute(
            "INSERT INTO reposcope.idempotency_requests "
            "(principal_id, route, idempotency_key, fingerprint, response, "
            "job_id, run_id, created_at, expires_at) "
            "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
            (
                submission.principal_id,
                route,
                submission.key,
                submission.fingerprint,
                response.model_dump_json(),
                job_id,
                run_id,
                submission.now,
                submission.now + timedelta(days=7),
            ),
        )

    async def create_repository(
        self,
        request: RepositoryCreate,
        submission: Submission,
        policy: AdmissionPolicy,
    ) -> RepositoryAccepted:
        async with self._transaction(admission=True) as connection:
            replay = await self._replay(
                connection, submission, "/v1/repositories", RepositoryAccepted
            )
            if replay is not None:
                return replay
            await self._admit(connection, submission, policy, run=False)
            repository = await _read(
                connection,
                "INSERT INTO reposcope.repositories (repository_id, principal_id, url, created_at) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (principal_id,url) "
                "DO UPDATE SET url=EXCLUDED.url "
                "RETURNING json_build_object('repository_id', repository_id)::text AS data",
                (uuid4(), submission.principal_id, request.url, submission.now),
                RepositoryIdentity,
            )
            if repository is None:
                raise WorkError("INTERNAL_ERROR")
            generation_id, job_id = uuid4(), uuid4()
            await connection.execute(
                "INSERT INTO reposcope.index_generations "
                "(generation_id, repository_id, principal_id, requested_ref, "
                "created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    generation_id,
                    repository.repository_id,
                    submission.principal_id,
                    request.requested_ref,
                    submission.now,
                    submission.now,
                ),
            )
            await connection.execute(
                "INSERT INTO reposcope.jobs "
                "(job_id, repository_id, generation_id, principal_id, requested_ref, status, "
                "deadline_at, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,'queued',%s,%s,%s)",
                (
                    job_id,
                    repository.repository_id,
                    generation_id,
                    submission.principal_id,
                    request.requested_ref,
                    submission.now + timedelta(minutes=30),
                    submission.now,
                    submission.now,
                ),
            )
            await connection.execute(
                "UPDATE reposcope.repositories SET latest_requested_generation_id=%s "
                "WHERE repository_id=%s",
                (generation_id, repository.repository_id),
            )
            accepted = RepositoryAccepted(repository_id=repository.repository_id, job_id=job_id)
            event = IngestRequested(
                event_id=uuid4(),
                aggregate_id=job_id,
                trace_id=submission.trace_id,
                occurred_at=submission.now,
                payload=IngestPayload(
                    job_id=job_id,
                    repository_id=repository.repository_id,
                    requested_ref=request.requested_ref,
                    principal_id=submission.principal_id,
                ),
            )
            await self._record(connection, submission, accepted, event)
            return accepted

    async def create_run(
        self,
        request: RunCreate,
        submission: Submission,
        policy: AdmissionPolicy,
    ) -> RunAccepted:
        async with self._transaction(admission=True) as connection:
            replay = await self._replay(connection, submission, "/v1/runs", RunAccepted)
            if replay is not None:
                return replay
            snapshot = await _read(
                connection,
                "SELECT json_build_object('generation_id', g.generation_id, "
                "'commit_sha', g.commit_sha, "
                "'status', g.status)::text AS data FROM reposcope.repositories r "
                "LEFT JOIN reposcope.index_generations g ON g.generation_id=r.active_generation_id "
                "WHERE r.repository_id=%s AND r.principal_id=%s FOR UPDATE OF r",
                (request.repository_id, submission.principal_id),
                Snapshot,
            )
            if snapshot is None:
                raise WorkError("NOT_FOUND")
            if (
                snapshot.status != "ready"
                or snapshot.generation_id is None
                or snapshot.commit_sha is None
            ):
                raise WorkError("INDEX_NOT_READY")
            await self._admit(connection, submission, policy, run=True)
            run_id = uuid4()
            await connection.execute(
                "INSERT INTO reposcope.agent_runs "
                "(run_id, repository_id, generation_id, principal_id, commit_sha, question, "
                "status, deadline_at, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s)",
                (
                    run_id,
                    request.repository_id,
                    snapshot.generation_id,
                    submission.principal_id,
                    snapshot.commit_sha,
                    request.question,
                    submission.now + timedelta(seconds=120),
                    submission.now,
                    submission.now,
                ),
            )
            await connection.execute(
                "INSERT INTO reposcope.usage_reservations "
                "(reservation_id, run_id, principal_id, amount_usd, state, "
                "budget_day, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,'reserved',%s,%s,%s)",
                (
                    uuid4(),
                    run_id,
                    submission.principal_id,
                    policy.reservation_usd,
                    submission.now.date(),
                    submission.now,
                    submission.now,
                ),
            )
            accepted = RunAccepted(
                run_id=run_id,
                repository_id=request.repository_id,
                generation_id=snapshot.generation_id,
            )
            event = AgentRequested(
                event_id=uuid4(),
                aggregate_id=run_id,
                trace_id=submission.trace_id,
                occurred_at=submission.now,
                payload=AgentPayload(
                    run_id=run_id,
                    repository_id=request.repository_id,
                    generation_id=snapshot.generation_id,
                    commit_sha=snapshot.commit_sha,
                    principal_id=submission.principal_id,
                ),
            )
            await self._record(connection, submission, accepted, event)
            return accepted

    async def get_job(self, principal_id: UUID, job_id: UUID) -> JobView:
        async with self._transaction() as connection:
            result = await _read(
                connection,
                "SELECT row_to_json(view)::text AS data FROM (SELECT job_id, repository_id, "
                "status, "
                "attempts, progress_percent, commit_sha, failure_code, created_at, updated_at "
                "FROM reposcope.jobs WHERE principal_id=%s AND job_id=%s) view",
                (principal_id, job_id),
                JobView,
            )
            if result is None:
                raise WorkError("NOT_FOUND")
            return result

    async def get_run(self, principal_id: UUID, run_id: UUID) -> RunView:
        async with self._transaction() as connection:
            result = await _read(
                connection,
                "SELECT row_to_json(view)::text AS data FROM (SELECT run_id, repository_id, "
                "generation_id, "
                "status, result, failure_code, created_at, updated_at FROM reposcope.agent_runs "
                "WHERE principal_id=%s AND run_id=%s) view",
                (principal_id, run_id),
                RunView,
            )
            if result is None:
                raise WorkError("NOT_FOUND")
            return result
