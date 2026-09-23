"""Role lifecycle behavior independent of real network dependencies."""

from __future__ import annotations

import asyncio
import signal

import pytest
import uvicorn
from fastapi import FastAPI

from reposcope.roles import _ManagedUvicornServer, run_role
from reposcope.runtime import RuntimeResources
from reposcope.settings import RuntimeSettings


class ControlledProbe:
    """Minimal resource owner used to observe role shutdown."""

    closed: bool

    def __init__(self) -> None:
        self.closed = False

    async def database_migrated(self, version: str) -> bool:
        return True

    async def redis_available(self) -> bool:
        return True

    async def jetstream_available(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


def test_role_managed_uvicorn_server_does_not_install_its_own_signal_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The role owns shared signal handling when API and management servers run together."""
    application = FastAPI()
    server = _ManagedUvicornServer(uvicorn.Config(application, log_config=None))

    def reject_signal_handler(_: int, __: signal.Handlers | None) -> signal.Handlers | None:
        raise AssertionError("Uvicorn attempted to replace the role signal handler")

    monkeypatch.setattr(signal, "signal", reject_signal_handler)

    with server.capture_signals():
        assert server.should_exit is False


@pytest.mark.asyncio
async def test_api_role_stops_public_and_management_servers_then_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One role stop signal drains both API servers before their shared resources close."""
    probe = ControlledProbe()
    resources = RuntimeResources(probe=probe, probe_timeout_seconds=0.1)
    calls: list[tuple[int, bool]] = []

    async def connect(_: RuntimeSettings) -> RuntimeResources:
        return resources

    def request_shutdown(stopping: asyncio.Event) -> None:
        stopping.set()

    async def serve(
        _: object, host: str, port: int, stopping: asyncio.Event, shutdown_timeout_seconds: float
    ) -> None:
        calls.append((port, stopping.is_set()))

    monkeypatch.setattr(RuntimeResources, "connect", connect)
    monkeypatch.setattr("reposcope.roles._install_signal_handlers", request_shutdown)
    monkeypatch.setattr("reposcope.roles._serve", serve)
    settings = RuntimeSettings.from_values(
        {
            "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
            "REDIS_URL": "redis://redis:6379/0",
            "NATS_URL": "nats://nats:4222",
            "ROLE": "api",
            "PROVIDER_MODE": "mock",
        }
    )

    await run_role(settings)

    assert calls == [(8000, True), (9000, True)]
    assert probe.closed is True
