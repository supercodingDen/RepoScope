"""Dependency lifecycle and readiness probes for deployable RepoScope roles."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol, Self, cast

import nats
import redis.asyncio as redis
from nats.aio.client import Client as NatsClient
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from reposcope.metrics import DEPENDENCY_READY
from reposcope.settings import RuntimeSettings

INITIAL_MIGRATION_VERSION = "0007_run_events"
LOGGER = logging.getLogger("reposcope.runtime")


async def _ignore_nats_error(_: Exception) -> None:
    """Suppress SDK exception text because connection URLs can contain credentials."""


class DependencyProbe(Protocol):
    """The minimal external dependency surface used by the readiness controller."""

    async def database_migrated(self, version: str) -> bool:
        """Return whether PostgreSQL is reachable and contains the required migration."""

    async def redis_available(self) -> bool:
        """Return whether Redis can answer PING."""

    async def jetstream_available(self) -> bool:
        """Return whether the JetStream account can be queried."""

    async def close(self) -> None:
        """Close every dependency owned by this probe."""


@dataclass(slots=True)
class ManagedDependencyProbe:
    """Concrete dependency adapter owned by a runtime process."""

    database_pool: AsyncConnectionPool[AsyncConnection[tuple[str]]]
    redis_client: redis.Redis
    nats_client: NatsClient
    close_timeout_seconds: float = 2.0

    async def database_migrated(self, version: str) -> bool:
        """Probe PostgreSQL and the migration history used by runtime readiness."""
        async with self.database_pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                await cursor.execute(
                    "SELECT version FROM reposcope.schema_migrations WHERE version = %s",
                    (version,),
                )
                row = await cursor.fetchone()
        return row is not None and row[0] == version

    async def redis_available(self) -> bool:
        """Probe Redis without retaining application state in the cache."""
        result = cast(Awaitable[bool], self.redis_client.ping())
        return bool(await result)

    async def jetstream_available(self) -> bool:
        """Probe the broker's JetStream account rather than only its TCP listener."""
        if not self.nats_client.is_connected:
            return False
        try:
            await self.nats_client.jetstream().account_info()
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        return True

    async def close(self) -> None:
        """Close every owned client, even when one client cleanup fails."""
        for name, operation in (
            ("nats", self.nats_client.close()),
            ("redis", self.redis_client.aclose()),
            ("database", self.database_pool.close()),
        ):
            try:
                await asyncio.wait_for(operation, timeout=self.close_timeout_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.error("runtime_resource_close_failed", extra={"resource": name})


@dataclass(slots=True)
class RuntimeResources:
    """Own resources and provide bounded, cancellation-safe readiness probes."""

    probe: DependencyProbe
    probe_timeout_seconds: float
    close_timeout_seconds: float = 2.0

    @classmethod
    async def connect(cls, settings: RuntimeSettings) -> Self:
        """Open role dependencies within the configured startup deadline."""
        pool: AsyncConnectionPool[AsyncConnection[tuple[str]]] = AsyncConnectionPool(
            conninfo=settings.database_url.get_secret_value(),
            min_size=1,
            max_size=settings.database_pool_size,
            open=False,
        )
        redis_client: redis.Redis = redis.from_url(
            settings.redis_url.get_secret_value(),
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.database_pool_size,
        )
        nats_client: NatsClient | None = None
        try:
            await asyncio.wait_for(pool.open(), timeout=settings.startup_timeout_seconds)
            nats_client = await asyncio.wait_for(
                nats.connect(
                    settings.nats_url.get_secret_value(),
                    allow_reconnect=True,
                    connect_timeout=settings.startup_timeout_seconds,
                    error_cb=_ignore_nats_error,
                    max_reconnect_attempts=-1,
                    reconnect_time_wait=1,
                ),
                timeout=settings.startup_timeout_seconds,
            )
        except BaseException:
            if nats_client is not None:
                await nats_client.close()
            await redis_client.aclose()
            await pool.close()
            raise
        close_timeout_seconds = settings.shutdown_timeout_seconds / 3.0
        probe = ManagedDependencyProbe(pool, redis_client, nats_client, close_timeout_seconds)
        return cls(
            probe=probe,
            probe_timeout_seconds=settings.probe_timeout_seconds,
            close_timeout_seconds=settings.shutdown_timeout_seconds,
        )

    async def is_ready(self) -> bool:
        """Check all mandatory dependencies using independent bounded probes."""
        try:
            database, redis_ready, jetstream = await asyncio.gather(
                self._bounded(self.probe.database_migrated(INITIAL_MIGRATION_VERSION)),
                self._bounded(self.probe.redis_available()),
                self._bounded(self.probe.jetstream_available()),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            for name in ("database", "redis", "jetstream"):
                DEPENDENCY_READY.labels(dependency=name).set(0)
            return False
        for name, available in (
            ("database", database),
            ("redis", redis_ready),
            ("jetstream", jetstream),
        ):
            DEPENDENCY_READY.labels(dependency=name).set(int(available))
        return database and redis_ready and jetstream

    async def _bounded(self, operation: Awaitable[bool]) -> bool:
        """Limit one dependency operation without translating cancellation to failure."""
        try:
            return await asyncio.wait_for(operation, timeout=self.probe_timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            return False

    async def close(self) -> None:
        """Close owned resources without extending role shutdown indefinitely."""
        try:
            await asyncio.wait_for(self.probe.close(), timeout=self.close_timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.error(
                "runtime_resource_close_failed",
                extra={"event": "runtime_resource_close_failed"},
            )
