"""Verify the production JetStream client recovers against an operator-supplied NATS binary."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from reposcope.logging_config import configure_logging
from reposcope.runtime import RuntimeResources
from reposcope.settings import RuntimeSettings

pytestmark = pytest.mark.integration


def _start_server(binary: Path, port: int, storage: Path) -> subprocess.Popen[bytes]:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(
        [str(binary), "-a", "127.0.0.1", "-p", str(port), "-js", "-sd", str(storage)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )


def _stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


async def _wait_for_port(port: int) -> None:
    async with asyncio.timeout(10):
        while True:
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                return
            except OSError:
                await asyncio.sleep(0.1)


async def _jetstream_available(resources: RuntimeResources) -> bool:
    try:
        async with asyncio.timeout(1):
            return await resources.probe.jetstream_available()
    except Exception:
        return False


@pytest.mark.asyncio
async def test_real_jetstream_client_recovers_after_broker_restart(tmp_path: Path) -> None:
    binary_value = os.environ.get("NATS_SERVER_BINARY")
    if not binary_value:
        pytest.skip("Set NATS_SERVER_BINARY to a trusted local test-server executable.")
    binary = Path(binary_value).resolve()
    assert binary.is_file(), "NATS_SERVER_BINARY must name an existing executable"
    configure_logging()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    process = _start_server(binary, port, tmp_path / "jetstream")
    resources: RuntimeResources | None = None
    try:
        await _wait_for_port(port)
        settings = RuntimeSettings.from_values(
            {
                "DATABASE_URL": "postgresql://fixture:fixture@127.0.0.1:1/fixture",
                "REDIS_URL": "redis://127.0.0.1:1/0",
                "NATS_URL": f"nats://127.0.0.1:{port}",
                "PROVIDER_MODE": "mock",
                "ALLOW_PAID_API_CALLS": "false",
            }
        )
        resources = await RuntimeResources.connect(settings)
        assert await _jetstream_available(resources)
        await asyncio.to_thread(_stop_server, process)
        await asyncio.sleep(0.1)
        assert not await _jetstream_available(resources)
        process = _start_server(binary, port, tmp_path / "jetstream")
        await _wait_for_port(port)
        async with asyncio.timeout(15):
            while not await _jetstream_available(resources):
                await asyncio.sleep(0.2)
        assert await _jetstream_available(resources)
    finally:
        if resources is not None:
            await resources.close()
        await asyncio.to_thread(_stop_server, process)
