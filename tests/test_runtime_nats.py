"""NATS connection recovery configuration for the T02 runtime."""

from __future__ import annotations

import nats
import pytest
import redis.asyncio as redis

import reposcope.runtime as runtime
from reposcope.runtime import RuntimeResources
from reposcope.settings import RuntimeSettings


class Pool:
    """Pool double used to isolate connection-option behavior."""

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


class RedisClient:
    """Redis double used to isolate connection-option behavior."""

    async def aclose(self) -> None:
        return None


class NatsClient:
    """NATS double used to isolate connection-option behavior."""

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_nats_connection_keeps_recovering_after_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temporary broker outage cannot permanently close the runtime NATS client."""
    received: dict[str, object] = {}

    def create_pool(*_: object, **__: object) -> Pool:
        return Pool()

    def create_redis(*_: object, **__: object) -> RedisClient:
        return RedisClient()

    async def connect(_: str, **options: object) -> NatsClient:
        received.update(options)
        return NatsClient()

    monkeypatch.setattr(runtime, "AsyncConnectionPool", create_pool)
    monkeypatch.setattr(redis, "from_url", create_redis)
    monkeypatch.setattr(nats, "connect", connect)
    settings = RuntimeSettings.from_values(
        {
            "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
            "REDIS_URL": "redis://redis:6379/0",
            "NATS_URL": "nats://nats:4222",
        }
    )

    resources = await RuntimeResources.connect(settings)

    assert received["allow_reconnect"] is True
    assert received["max_reconnect_attempts"] == -1
    assert received["reconnect_time_wait"] == 1
    callback = received["error_cb"]
    assert callable(callback)
    await resources.close()
