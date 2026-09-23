"""Readiness behavior for the T02 runtime."""

from __future__ import annotations

import asyncio

import pytest
import redis.asyncio as redis
from nats.aio.client import Client as NatsClient
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from reposcope.runtime import INITIAL_MIGRATION_VERSION, ManagedDependencyProbe, RuntimeResources


class ReadyDependencies:
    """In-memory dependency probe that reports a ready runtime."""

    closed: bool

    def __init__(self) -> None:
        self.closed = False

    async def database_migrated(self, version: str) -> bool:
        return version == INITIAL_MIGRATION_VERSION

    async def redis_available(self) -> bool:
        return True

    async def jetstream_available(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


class RedisOutage(ReadyDependencies):
    """A dependency probe whose Redis operation fails."""

    async def redis_available(self) -> bool:
        raise ConnectionError("redis unavailable")


class SlowDatabase(ReadyDependencies):
    """A dependency probe that exceeds its bounded health timeout."""

    async def database_migrated(self, version: str) -> bool:
        await asyncio.sleep(1)
        return True


class CancelledProbe(ReadyDependencies):
    """A dependency probe that verifies cancellation is never converted to readiness false."""

    async def redis_available(self) -> bool:
        raise asyncio.CancelledError


class FailingNatsClose(NatsClient):
    """NATS close double that exercises cleanup after a broker client failure."""

    async def close(self) -> None:
        raise ConnectionError("nats close failed")


class TrackingRedisClose(redis.Redis):
    """Redis close double that records independent cleanup."""

    closed: bool

    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def aclose(self, close_connection_pool: bool | None = None) -> None:
        self.closed = True


class TrackingPoolClose(AsyncConnectionPool[AsyncConnection[tuple[str]]]):
    """Pool close double that records independent cleanup."""

    close_called: bool

    def __init__(self) -> None:
        super().__init__(conninfo="postgresql://runtime:secret@postgres/reposcope", open=False)
        self.close_called = False

    async def close(self, timeout: float = 5.0) -> None:
        self.close_called = True


@pytest.mark.asyncio
async def test_readiness_requires_database_migration_redis_and_jetstream() -> None:
    """A working liveness process is ready only when every owned dependency is ready."""
    resources = RuntimeResources(probe=ReadyDependencies(), probe_timeout_seconds=0.1)

    assert await resources.is_ready() is True

    outage = RuntimeResources(probe=RedisOutage(), probe_timeout_seconds=0.1)
    assert await outage.is_ready() is False


@pytest.mark.asyncio
async def test_readiness_treats_a_timed_out_probe_as_unready() -> None:
    """An unavailable dependency cannot leave readiness waiting indefinitely."""
    resources = RuntimeResources(probe=SlowDatabase(), probe_timeout_seconds=0.01)

    assert await resources.is_ready() is False


@pytest.mark.asyncio
async def test_readiness_propagates_task_cancellation() -> None:
    """Shutdown cancellation must not be silently reported as a dependency outage."""
    resources = RuntimeResources(probe=CancelledProbe(), probe_timeout_seconds=0.1)

    with pytest.raises(asyncio.CancelledError):
        await resources.is_ready()


@pytest.mark.asyncio
async def test_resource_lifecycle_closes_owned_dependencies() -> None:
    """Role shutdown closes every resource it owns exactly through its lifecycle boundary."""
    dependencies = ReadyDependencies()
    resources = RuntimeResources(probe=dependencies, probe_timeout_seconds=0.1)

    await resources.close()

    assert dependencies.closed is True


@pytest.mark.asyncio
async def test_managed_close_releases_redis_and_database_after_nats_close_failure() -> None:
    """One client-close failure cannot leak the remaining owned resource clients."""
    redis_client = TrackingRedisClose()
    database_pool = TrackingPoolClose()
    probe = ManagedDependencyProbe(database_pool, redis_client, FailingNatsClose())

    await probe.close()

    assert redis_client.closed is True
    assert database_pool.close_called is True
