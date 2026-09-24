"""Durable, ordered run-event writes and bounded replay reads."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from contracts.models import CompletedData, FailedData, RunEvent, StartedData, ToolData
from reposcope.domain.errors import WorkError
from reposcope.ports.run_events import EventBatch

type RunEventData = StartedData | ToolData | CompletedData | FailedData


def decode_db_run_event(run_id: UUID, sequence: int, occurred_at: datetime, data: str) -> RunEvent:
    """Validate stored JSON in JSON mode so nested UUID strings retain strict typing."""
    return RunEvent.model_validate_json(
        json.dumps(
            {
                "run_id": str(run_id),
                "sequence": sequence,
                "occurred_at": occurred_at.isoformat(),
                "data": json.loads(data),
            }
        )
    )


async def append_run_event(
    connection: AsyncConnection[tuple[str]], run_id: UUID, data: RunEventData
) -> int:
    """Allocate a sequence while holding the run row lock in the caller's transaction."""
    cursor = await connection.execute(
        "SELECT run_id FROM reposcope.agent_runs WHERE run_id=%s FOR UPDATE", (run_id,)
    )
    if await cursor.fetchone() is None:
        raise ValueError("Run not found")
    cursor = await connection.execute(
        "SELECT coalesce(max(sequence),0)+1 FROM reposcope.run_events WHERE run_id=%s",
        (run_id,),
    )
    row = cast(tuple[int] | None, await cursor.fetchone())
    assert row is not None
    sequence = row[0]
    await connection.execute(
        "INSERT INTO reposcope.run_events(run_id,sequence,data) VALUES(%s,%s,%s::jsonb)",
        (run_id, sequence, data.model_dump_json()),
    )
    return sequence


class PostgresRunEvents:
    """Principal-scoped replay with database-wide expiring connection slots."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[tuple[str]]]) -> None:
        self.pool = pool

    async def open(self, principal_id: UUID, run_id: UUID, after: int) -> UUID:
        if after < 0:
            raise WorkError("VALIDATION_ERROR")
        async with asyncio.timeout(10), self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(721044)")
                cursor = await connection.execute(
                    "SELECT status,updated_at,"
                    "(SELECT coalesce(max(sequence),0) FROM reposcope.run_events e "
                    "WHERE e.run_id=r.run_id) FROM reposcope.agent_runs r "
                    "WHERE run_id=%s AND principal_id=%s",
                    (run_id, principal_id),
                )
                row = cast(tuple[str, datetime, int] | None, await cursor.fetchone())
                if row is None:
                    raise WorkError("NOT_FOUND")
                status, updated_at, maximum = row
                cursor = await connection.execute(
                    "SELECT clock_timestamp()-interval '24 hours',clock_timestamp()"
                )
                clock = cast(tuple[datetime, datetime] | None, await cursor.fetchone())
                assert clock is not None
                if status in ("succeeded", "failed") and updated_at < clock[0]:
                    raise WorkError("EVENT_CURSOR_EXPIRED")
                if after > maximum:
                    raise WorkError("VALIDATION_ERROR")
                await connection.execute(
                    "DELETE FROM reposcope.sse_connections WHERE expires_at<=clock_timestamp()"
                )
                cursor = await connection.execute(
                    "SELECT count(*)::integer,count(*) FILTER (WHERE principal_id=%s)::integer "
                    "FROM reposcope.sse_connections",
                    (principal_id,),
                )
                counts = cast(tuple[int, int] | None, await cursor.fetchone())
                assert counts is not None
                if counts[0] >= 20 or counts[1] >= 2:
                    raise WorkError("RATE_LIMITED")
                connection_id = uuid4()
                await connection.execute(
                    "INSERT INTO reposcope.sse_connections "
                    "(connection_id,principal_id,run_id,expires_at) "
                    "VALUES(%s,%s,%s,clock_timestamp()+interval '30 seconds')",
                    (connection_id, principal_id, run_id),
                )
                return connection_id

    async def batch(
        self, connection_id: UUID, principal_id: UUID, run_id: UUID, after: int
    ) -> EventBatch:
        async with asyncio.timeout(10), self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "UPDATE reposcope.sse_connections SET "
                    "expires_at=clock_timestamp()+interval '30 seconds' "
                    "WHERE connection_id=%s AND principal_id=%s AND run_id=%s "
                    "AND expires_at>clock_timestamp() RETURNING connection_id",
                    (connection_id, principal_id, run_id),
                )
                if await cursor.fetchone() is None:
                    raise WorkError("RATE_LIMITED")
                cursor = await connection.execute(
                    "SELECT sequence,occurred_at,data::text FROM reposcope.run_events "
                    "WHERE run_id=%s AND sequence>%s ORDER BY sequence LIMIT 100",
                    (run_id, after),
                )
                rows = cast(list[tuple[int, datetime, str]], await cursor.fetchall())
                events = tuple(
                    decode_db_run_event(run_id, sequence, occurred_at, data)
                    for sequence, occurred_at, data in rows
                )
                cursor = await connection.execute(
                    "SELECT status FROM reposcope.agent_runs WHERE run_id=%s AND principal_id=%s",
                    (run_id, principal_id),
                )
                status_row = await cursor.fetchone()
                if status_row is None:
                    raise WorkError("NOT_FOUND")
                return EventBatch(events, status_row[0] in ("succeeded", "failed"))

    async def release(self, connection_id: UUID) -> None:
        async with asyncio.timeout(10), self.pool.connection() as connection:
            await connection.execute(
                "DELETE FROM reposcope.sse_connections WHERE connection_id=%s", (connection_id,)
            )

    async def prune(self) -> int:
        """Delete old terminal timelines in bounded batches without deleting run results."""
        async with asyncio.timeout(10), self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM reposcope.sse_connections WHERE expires_at<=clock_timestamp()"
                )
                cursor = await connection.execute(
                    "DELETE FROM reposcope.run_events WHERE (run_id,sequence) IN ("
                    "SELECT e.run_id,e.sequence FROM reposcope.run_events e "
                    "JOIN reposcope.agent_runs r ON r.run_id=e.run_id "
                    "WHERE r.status IN ('succeeded','failed') "
                    "AND r.updated_at<clock_timestamp()-interval '24 hours' "
                    "ORDER BY e.run_id,e.sequence LIMIT 1000) RETURNING run_id"
                )
                return len(await cursor.fetchall())
