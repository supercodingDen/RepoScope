"""PostgreSQL fencing, publication claims, and atomic delivery completion."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from psycopg import AsyncConnection, sql
from psycopg_pool import AsyncConnectionPool

from contracts.models import (
    AgentRequested,
    CompletedData,
    Contract,
    FailedData,
    IngestRequested,
    SourceAcquired,
)
from reposcope.adapters.postgres_run_events import append_run_event
from reposcope.adapters.postgres_work import _read
from reposcope.domain.delivery import (
    Complete,
    DeliveryEvent,
    DeliveryPolicy,
    Lease,
    LeaseLost,
    OutboxClaim,
    PermanentFailure,
    parse_event,
    parse_publication,
)


class _Claim(Contract):
    payload: str
    fencing_token: int
    attempts: int


class _Work(Contract):
    deadline_at: datetime
    status: str
    attempts: int


class _LeaseState(Contract):
    fencing_token: int
    attempts: int
    deadline_at: datetime


def _table(event: DeliveryEvent) -> tuple[str, str, str]:
    if isinstance(event, IngestRequested):
        return "jobs", "job_id", "attempts"
    if isinstance(event, SourceAcquired):
        return "jobs", "job_id", "index_attempts"
    return "agent_runs", "run_id", "delivery_attempts"


class PostgresDeliveryRepository:
    def __init__(
        self,
        pool: AsyncConnectionPool[AsyncConnection[tuple[str]]],
        policy: DeliveryPolicy | None = None,
    ) -> None:
        self.pool = pool
        self.policy = policy or DeliveryPolicy()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection[tuple[str]]]:
        async with asyncio.timeout(10), self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL lock_timeout='3s'")
                await connection.execute("SET LOCAL statement_timeout='8s'")
                yield connection

    async def claim_outbox(self, owner: UUID) -> OutboxClaim | None:
        async with self.transaction() as connection:
            row = await _read(
                connection,
                "WITH candidate AS (SELECT o.event_id FROM reposcope.outbox_events o "
                "LEFT JOIN reposcope.jobs j ON j.job_id=o.job_id "
                "LEFT JOIN reposcope.agent_runs r ON r.run_id=o.run_id "
                "WHERE o.published_at IS NULL AND "
                "coalesce(j.status,r.status) IN ('queued','running') AND "
                "coalesce(j.deadline_at,r.deadline_at)>clock_timestamp() AND "
                "(o.lease_until IS NULL OR o.lease_until<=clock_timestamp()) AND "
                "(o.next_attempt_at IS NULL OR o.next_attempt_at<=clock_timestamp()) "
                "ORDER BY o.occurred_at FOR UPDATE OF o SKIP LOCKED LIMIT 1), "
                "claimed AS (UPDATE reposcope.outbox_events o SET lease_owner=%s, "
                "lease_until=clock_timestamp()+make_interval(secs=>%s), "
                "fencing_token=o.fencing_token+1,attempts=o.attempts+1 FROM candidate c "
                "WHERE o.event_id=c.event_id RETURNING o.payload::text,o.fencing_token,o.attempts) "
                "SELECT row_to_json(claimed)::text AS data FROM claimed",
                (owner, self.policy.lease_seconds),
                _Claim,
            )
            if row is None:
                return None
            return OutboxClaim(
                parse_publication(row.payload), owner, row.fencing_token, row.attempts
            )

    async def mark_published(self, claim: OutboxClaim) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                "SELECT event_id FROM reposcope.outbox_events WHERE event_id=%s FOR UPDATE",
                (claim.event.event_id,),
            )
            cursor = await connection.execute(
                "UPDATE reposcope.outbox_events SET published_at=clock_timestamp(), "
                "lease_owner=NULL,lease_until=NULL WHERE event_id=%s AND lease_owner=%s "
                "AND fencing_token=%s AND lease_until>clock_timestamp() AND published_at IS NULL",
                (claim.event.event_id, claim.owner, claim.token),
            )
            if cursor.rowcount != 1:
                raise LeaseLost()

    async def retry_publication(self, claim: OutboxClaim, delay: float) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                "SELECT event_id FROM reposcope.outbox_events WHERE event_id=%s FOR UPDATE",
                (claim.event.event_id,),
            )
            await connection.execute(
                "UPDATE reposcope.outbox_events SET next_attempt_at=clock_timestamp()+ "
                "make_interval(secs=>%s),lease_owner=NULL,lease_until=NULL "
                "WHERE event_id=%s AND lease_owner=%s AND fencing_token=%s "
                "AND lease_until>clock_timestamp() AND published_at IS NULL",
                (delay, claim.event.event_id, claim.owner, claim.token),
            )

    async def authorized(self, event: DeliveryEvent) -> bool:
        table, key, _ = _table(event)
        async with self.transaction() as connection:
            query = sql.SQL(
                "SELECT o.event_id::text FROM reposcope.outbox_events o JOIN reposcope.{} w "
                "ON w.{}=o.aggregate_id WHERE o.event_id=%s AND o.payload=%s::jsonb "
                "AND o.principal_id=%s AND w.principal_id=%s AND w.repository_id=%s "
                "AND o.event_type=%s AND o.aggregate_id=%s AND o.trace_id=%s "
                "AND o.occurred_at=%s "
            ).format(sql.Identifier(table), sql.Identifier(key))
            parameters: list[object] = [
                event.event_id,
                event.model_dump_json(),
                event.payload.principal_id,
                event.payload.principal_id,
                event.payload.repository_id,
                event.event_type,
                event.aggregate_id,
                event.trace_id,
                event.occurred_at,
            ]
            if isinstance(event, IngestRequested):
                query += sql.SQL("AND w.requested_ref=%s")
                parameters.append(event.payload.requested_ref)
            elif isinstance(event, SourceAcquired):
                query += sql.SQL(
                    "AND w.generation_id=%s AND w.commit_sha=%s AND EXISTS ("
                    "SELECT 1 FROM reposcope.source_manifests m WHERE m.job_id=w.job_id "
                    "AND m.repository_id=%s AND m.generation_id=%s AND m.principal_id=%s "
                    "AND m.commit_sha=%s AND m.manifest_digest=%s)"
                )
                parameters.extend(
                    [
                        event.payload.generation_id,
                        event.payload.commit_sha,
                        event.payload.repository_id,
                        event.payload.generation_id,
                        event.payload.principal_id,
                        event.payload.commit_sha,
                        event.payload.manifest_digest,
                    ]
                )
            else:
                query += sql.SQL(
                    "AND w.generation_id=%s AND w.commit_sha=%s AND w.policy_version=%s"
                )
                parameters.extend(
                    [
                        event.payload.generation_id,
                        event.payload.commit_sha,
                        event.payload.policy_version,
                    ]
                )
            cursor = await connection.execute(query, parameters)
            return await cursor.fetchone() is not None

    async def quarantine(self, data: bytes, consumer: str, reason: str) -> None:
        fingerprint = hashlib.sha256(data).hexdigest()
        async with self.transaction() as connection:
            # Bound cardinality and retention. Serialization prevents a concurrent capacity bypass.
            await connection.execute("SELECT pg_advisory_xact_lock(721043)")
            await connection.execute(
                "DELETE FROM reposcope.delivery_quarantine "
                "WHERE last_seen_at<clock_timestamp()-interval '7 days'"
            )
            await connection.execute(
                "DELETE FROM reposcope.delivery_quarantine WHERE fingerprint IN "
                "(SELECT fingerprint FROM reposcope.delivery_quarantine "
                "ORDER BY last_seen_at DESC OFFSET 9999)"
            )
            await connection.execute(
                "INSERT INTO reposcope.delivery_quarantine(fingerprint,reason,consumer,byte_count) "
                "VALUES(%s,%s,%s,%s) ON CONFLICT(fingerprint) DO UPDATE "
                "SET occurrences=least(delivery_quarantine.occurrences+1,2147483647), "
                "last_seen_at=clock_timestamp()",
                (fingerprint, reason, consumer, min(len(data), 65536)),
            )

    async def completed(self, consumer: str, event_id: UUID) -> bool:
        async with self.transaction() as connection:
            cursor = await connection.execute(
                "SELECT event_id::text FROM reposcope.consumer_work WHERE consumer=%s "
                "AND event_id=%s AND completed_at IS NOT NULL",
                (consumer, event_id),
            )
            return await cursor.fetchone() is not None

    async def claim(self, event: DeliveryEvent, consumer: str, owner: UUID) -> Lease | None:
        table, key, attempts = _table(event)
        async with self.transaction() as connection:
            await connection.execute(
                sql.SQL(
                    "INSERT INTO reposcope.consumer_work(consumer,event_id,deadline_at) "
                    "SELECT %s,%s,deadline_at FROM reposcope.{} WHERE {}=%s "
                    "ON CONFLICT DO NOTHING"
                ).format(sql.Identifier(table), sql.Identifier(key)),
                (consumer, event.event_id, event.aggregate_id),
            )
            await connection.execute(
                "SELECT event_id FROM reposcope.consumer_work "
                "WHERE consumer=%s AND event_id=%s FOR UPDATE",
                (consumer, event.event_id),
            )
            await connection.execute(
                sql.SQL("SELECT {} FROM reposcope.{} WHERE {}=%s FOR UPDATE").format(
                    sql.Identifier(key), sql.Identifier(table), sql.Identifier(key)
                ),
                (event.aggregate_id,),
            )
            cursor = await connection.execute(
                "SELECT event_id::text FROM reposcope.consumer_work WHERE consumer=%s AND "
                "event_id=%s "
                "AND completed_at IS NULL AND (lease_until IS NULL OR "
                "lease_until<=clock_timestamp()) "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=clock_timestamp()) "
                "FOR UPDATE",
                (consumer, event.event_id),
            )
            if await cursor.fetchone() is None:
                return None
            work = await _read(
                connection,
                sql.SQL(
                    "SELECT "
                    "json_build_object('deadline_at',deadline_at,'status',status,"
                    "'attempts',{})::text AS data "
                    "FROM reposcope.{} WHERE {}=%s AND status IN ('queued','running') "
                    "AND deadline_at>clock_timestamp() AND {}<%s FOR UPDATE"
                ).format(
                    sql.Identifier(attempts),
                    sql.Identifier(table),
                    sql.Identifier(key),
                    sql.Identifier(attempts),
                ),
                (event.aggregate_id, self.policy.max_attempts),
                _Work,
            )
            if work is None:
                return None
            state = await _read(
                connection,
                "WITH updated AS (UPDATE reposcope.consumer_work SET lease_owner=%s, "
                "lease_until=clock_timestamp()+make_interval(secs=>%s),"
                "fencing_token=fencing_token+1, "
                "attempts=attempts+1 WHERE consumer=%s AND event_id=%s "
                "RETURNING fencing_token,attempts,deadline_at) SELECT "
                "row_to_json(updated)::text AS data FROM updated",
                (owner, self.policy.lease_seconds, consumer, event.event_id),
                _LeaseState,
            )
            assert state is not None
            await connection.execute(
                sql.SQL(
                    "UPDATE reposcope.{} SET status='running',{}={}+1,lease_owner=%s, "
                    "lease_until=clock_timestamp()+make_interval(secs=>%s),fencing_token=%s, "
                    "updated_at=clock_timestamp() WHERE {}=%s"
                ).format(
                    sql.Identifier(table),
                    sql.Identifier(attempts),
                    sql.Identifier(attempts),
                    sql.Identifier(key),
                ),
                (owner, self.policy.lease_seconds, state.fencing_token, event.aggregate_id),
            )
            return Lease(
                event, consumer, owner, state.fencing_token, work.deadline_at, work.attempts + 1
            )

    async def lock_lease(self, connection: AsyncConnection[tuple[str]], lease: Lease) -> None:
        """Call inside checkpoint transaction; locks remain held through its commit."""
        # Lock by identity first. An unexpired WHERE predicate before a lock wait
        # is not a fresh ownership check when the blocker only held the row lock.
        await connection.execute(
            "SELECT event_id FROM reposcope.consumer_work WHERE consumer=%s AND event_id=%s FOR "
            "UPDATE",
            (lease.consumer, lease.event.event_id),
        )
        table, key, _ = _table(lease.event)
        await connection.execute(
            sql.SQL("SELECT {} FROM reposcope.{} WHERE {}=%s FOR UPDATE").format(
                sql.Identifier(key), sql.Identifier(table), sql.Identifier(key)
            ),
            (lease.event.aggregate_id,),
        )
        cursor = await connection.execute(
            "SELECT event_id::text FROM reposcope.consumer_work WHERE consumer=%s AND event_id=%s "
            "AND lease_owner=%s AND fencing_token=%s AND lease_until>clock_timestamp() "
            "AND deadline_at>clock_timestamp() AND completed_at IS NULL",
            (lease.consumer, lease.event.event_id, lease.owner, lease.token),
        )
        if await cursor.fetchone() is None:
            raise LeaseLost()
        cursor = await connection.execute(
            sql.SQL(
                "SELECT {}::text FROM reposcope.{} WHERE {}=%s AND lease_owner=%s AND "
                "fencing_token=%s "
                "AND lease_until>clock_timestamp() AND deadline_at>clock_timestamp() "
                "AND status='running'"
            ).format(sql.Identifier(key), sql.Identifier(table), sql.Identifier(key)),
            (lease.event.aggregate_id, lease.owner, lease.token),
        )
        if await cursor.fetchone() is None:
            raise LeaseLost()

    async def renew(self, lease: Lease) -> None:
        async with self.transaction() as connection:
            await self.lock_lease(connection, lease)
            await connection.execute(
                "UPDATE reposcope.consumer_work SET lease_until= "
                "clock_timestamp()+make_interval(secs=>%s) WHERE consumer=%s AND event_id=%s",
                (self.policy.lease_seconds, lease.consumer, lease.event.event_id),
            )
            table, key, _ = _table(lease.event)
            await connection.execute(
                sql.SQL(
                    "UPDATE reposcope.{} SET lease_until= "
                    "clock_timestamp()+make_interval(secs=>%s) WHERE {}=%s"
                ).format(sql.Identifier(table), sql.Identifier(key)),
                (self.policy.lease_seconds, lease.event.aggregate_id),
            )

    async def release(self, lease: Lease, delay: float, *, refund_attempt: bool = False) -> None:
        async with self.transaction() as connection:
            await self.lock_lease(connection, lease)
            await connection.execute(
                "UPDATE reposcope.consumer_work SET lease_owner=NULL,lease_until=NULL, "
                "next_attempt_at=clock_timestamp()+make_interval(secs=>%s),attempts=attempts-%s "
                "WHERE consumer=%s AND event_id=%s",
                (delay, int(refund_attempt), lease.consumer, lease.event.event_id),
            )
            table, key, attempts = _table(lease.event)
            await connection.execute(
                sql.SQL(
                    "UPDATE reposcope.{} SET status='queued',lease_owner=NULL, "
                    "lease_until=NULL,next_attempt_at=clock_timestamp()+make_interval(secs=>%s), "
                    "{}={}- %s,updated_at=clock_timestamp() WHERE {}=%s"
                ).format(
                    sql.Identifier(table),
                    sql.Identifier(attempts),
                    sql.Identifier(attempts),
                    sql.Identifier(key),
                ),
                (delay, int(refund_attempt), lease.event.aggregate_id),
            )

    async def complete_stage(self, connection: AsyncConnection[tuple[str]], lease: Lease) -> None:
        """T05 hook: same transaction MUST persist its checkpoint and continuation first."""
        await self.lock_lease(connection, lease)
        await self._completion(connection, lease.consumer, lease.event, "staged", None)

    async def _completion(
        self,
        connection: AsyncConnection[tuple[str]],
        consumer: str,
        event: DeliveryEvent,
        outcome: str,
        code: str | None,
    ) -> None:
        await connection.execute(
            "INSERT INTO reposcope.delivery_completions "
            "(consumer,event_id,aggregate_id,outcome,failure_code) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT (consumer,event_id) DO UPDATE SET outcome=excluded.outcome, "
            "failure_code=excluded.failure_code,completed_at=excluded.completed_at "
            "WHERE delivery_completions.outcome='staged' AND excluded.outcome IN "
            "('failed','succeeded')",
            (consumer, event.event_id, event.aggregate_id, outcome, code),
        )
        await connection.execute(
            "UPDATE reposcope.consumer_work SET completed_at=clock_timestamp(), "
            "lease_owner=NULL,lease_until=NULL WHERE consumer=%s AND event_id=%s",
            (consumer, event.event_id),
        )

    async def finalize(self, lease: Lease, outcome: Complete | PermanentFailure) -> None:
        async with self.transaction() as connection:
            await self.lock_lease(connection, lease)
            failure = outcome.code if isinstance(outcome, PermanentFailure) else None
            status = "failed" if failure else "succeeded"
            table, key, _ = _table(lease.event)
            if isinstance(lease.event, SourceAcquired) and isinstance(outcome, Complete):
                raise ValueError("Index completion requires atomic generation publication")
            if isinstance(lease.event, AgentRequested) and isinstance(outcome, Complete):
                if outcome.result is None:
                    raise ValueError("Agent completion requires a validated result")
                for citation in outcome.result.citations:
                    if (citation.repository_id, citation.generation_id, citation.commit_sha) != (
                        lease.event.payload.repository_id,
                        lease.event.payload.generation_id,
                        lease.event.payload.commit_sha,
                    ):
                        raise ValueError("Result scope mismatch")
                await connection.execute(
                    "UPDATE reposcope.agent_runs SET result=%s::jsonb, "
                    "status='succeeded',lease_owner=NULL,lease_until=NULL,"
                    "updated_at=clock_timestamp() "
                    "WHERE run_id=%s",
                    (outcome.result.model_dump_json(), lease.event.aggregate_id),
                )
            else:
                extra = sql.SQL(",progress_percent=100") if status == "succeeded" else sql.SQL("")
                if isinstance(lease.event, IngestRequested) and status == "succeeded":
                    cursor = await connection.execute(
                        "SELECT generation_id::text FROM reposcope.index_generations "
                        "WHERE generation_id=(SELECT generation_id FROM reposcope.jobs WHERE "
                        "job_id=%s) "
                        "AND status='ready'",
                        (lease.event.aggregate_id,),
                    )
                    if await cursor.fetchone() is None:
                        raise ValueError("Ingestion completion requires a ready generation")
                await connection.execute(
                    sql.SQL(
                        "UPDATE reposcope.{} SET status=%s,failure_code=%s, "
                        "lease_owner=NULL,lease_until=NULL,updated_at=clock_timestamp(){}"
                    ).format(sql.Identifier(table), extra)
                    + sql.SQL(" WHERE {}=%s").format(sql.Identifier(key)),
                    (status, failure, lease.event.aggregate_id),
                )
            if failure and isinstance(lease.event, (IngestRequested, SourceAcquired)):
                await connection.execute(
                    "UPDATE reposcope.index_generations SET status='failed', "
                    "updated_at=clock_timestamp() WHERE generation_id=(SELECT generation_id FROM "
                    "reposcope.jobs WHERE job_id=%s) AND status IN ('pending','staged')",
                    (lease.event.aggregate_id,),
                )
            if isinstance(lease.event, AgentRequested):
                data = (
                    FailedData(code=failure, message="The run could not be completed.")
                    if failure is not None
                    else CompletedData(result=outcome.result)
                    if isinstance(outcome, Complete) and outcome.result is not None
                    else None
                )
                if data is None:
                    raise ValueError("Agent outcome is incomplete")
                await append_run_event(connection, lease.event.aggregate_id, data)
            await self._completion(connection, lease.consumer, lease.event, status, failure)

    async def reconcile(self) -> int:
        """Finite DB deadlines cover broker max-deliver and never-delivered messages."""
        count = 0
        async with self.transaction() as connection:
            # Consistent consumer-before-business lock ordering with checkpoint/finalizer.
            cursor = await connection.execute(
                "SELECT payload::text FROM reposcope.outbox_events o "
                "LEFT JOIN reposcope.jobs j ON j.job_id=o.job_id LEFT JOIN reposcope.agent_runs "
                "r ON r.run_id=o.run_id "
                "WHERE o.event_type IN ('repo.ingest.requested','repo.source.acquired',"
                "'agent.run.requested') AND "
                "coalesce(j.status,r.status) IN ('queued','running') AND "
                "(coalesce(j.deadline_at,r.deadline_at)<=clock_timestamp() OR "
                "((CASE WHEN o.event_type='repo.source.acquired' THEN j.index_attempts "
                "ELSE coalesce(j.attempts,r.delivery_attempts) END)>=5 AND NOT EXISTS "
                "(SELECT 1 FROM reposcope.consumer_work c WHERE c.event_id=o.event_id "
                "AND c.completed_at IS NOT NULL) AND "
                "(coalesce(j.lease_until,r.lease_until) IS NULL OR "
                "coalesce(j.lease_until,r.lease_until)<=clock_timestamp()))) LIMIT 100"
            )
            payloads = await cursor.fetchall()
            for row in payloads:
                event = parse_event(row[0])
                table, key, attempts = _table(event)
                consumer = (
                    "indexer"
                    if isinstance(event, IngestRequested)
                    else "source"
                    if isinstance(event, SourceAcquired)
                    else "agent"
                )
                await connection.execute(
                    sql.SQL(
                        "INSERT INTO reposcope.consumer_work "
                        "(consumer,event_id,deadline_at) SELECT %s,%s,deadline_at FROM "
                        "reposcope.{} "
                        "WHERE {}=%s ON CONFLICT DO NOTHING"
                    ).format(sql.Identifier(table), sql.Identifier(key)),
                    (consumer, event.event_id, event.aggregate_id),
                )
                await connection.execute(
                    "SELECT event_id FROM reposcope.consumer_work "
                    "WHERE consumer=%s AND event_id=%s FOR UPDATE",
                    (consumer, event.event_id),
                )
                updated = await connection.execute(
                    sql.SQL(
                        "UPDATE reposcope.{} SET status='failed', "
                        "failure_code=CASE WHEN deadline_at<=clock_timestamp() THEN "
                        "'DEADLINE_EXCEEDED' "
                        "ELSE 'ATTEMPTS_EXHAUSTED' END,lease_owner=NULL,lease_until=NULL, "
                        "updated_at=clock_timestamp() WHERE {}=%s AND status IN "
                        "('queued','running') "
                        "AND (deadline_at<=clock_timestamp() OR ({}>=5 AND NOT EXISTS "
                        "(SELECT 1 FROM reposcope.consumer_work c WHERE c.event_id=%s "
                        "AND c.completed_at IS NOT NULL) AND "
                        "(lease_until IS NULL OR lease_until<=clock_timestamp()))) RETURNING "
                        "failure_code"
                    ).format(sql.Identifier(table), sql.Identifier(key), sql.Identifier(attempts)),
                    (event.aggregate_id, event.event_id),
                )
                failure = await updated.fetchone()
                if failure is None:
                    continue
                if isinstance(event, AgentRequested):
                    await append_run_event(
                        connection,
                        event.aggregate_id,
                        FailedData(code=failure[0], message="The run could not be completed."),
                    )
                await self._completion(connection, consumer, event, "failed", failure[0])
                if isinstance(event, (IngestRequested, SourceAcquired)):
                    await connection.execute(
                        "UPDATE reposcope.index_generations SET status='failed', "
                        "updated_at=clock_timestamp() WHERE generation_id=(SELECT generation_id "
                        "FROM "
                        "reposcope.jobs WHERE job_id=%s) AND status IN ('pending','staged')",
                        (event.aggregate_id,),
                    )
                count += 1
            await connection.execute(
                "UPDATE reposcope.outbox_events SET lease_owner=NULL,lease_until=NULL "
                "WHERE published_at IS NULL AND lease_until<=clock_timestamp()"
            )
            # Expired claims remain available with their durable counters preserved.
        return count
