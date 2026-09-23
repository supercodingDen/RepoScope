"""Read-only, bounded operational backlog query."""

from __future__ import annotations

import asyncio
from typing import cast

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


class PostgresOperationalRepository:
    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[tuple[str]]]) -> None:
        self.pool = pool

    async def snapshot(self) -> tuple[int, int, int]:
        async with asyncio.timeout(5), self.pool.connection(timeout=5) as connection:
            cursor = await connection.execute(
                "SELECT "
                "(SELECT count(*)::integer FROM reposcope.jobs "
                "WHERE status IN ('queued','running')),"
                "(SELECT count(*)::integer FROM reposcope.agent_runs "
                "WHERE status IN ('queued','running')),"
                "(SELECT count(*)::integer FROM reposcope.outbox_events o "
                "LEFT JOIN reposcope.jobs j ON j.job_id=o.job_id "
                "LEFT JOIN reposcope.agent_runs r ON r.run_id=o.run_id "
                "WHERE o.published_at IS NULL "
                "AND coalesce(j.status,r.status) IN ('queued','running') "
                "AND coalesce(j.deadline_at,r.deadline_at)>clock_timestamp())"
            )
            row = cast(tuple[int, int, int] | None, await cursor.fetchone())
            if row is None:
                raise RuntimeError("Missing work snapshot")
            return row
