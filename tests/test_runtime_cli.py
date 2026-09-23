"""CLI startup safety and role selection contracts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import reposcope.__main__ as command
from reposcope.settings import RuntimeSettings

ROOT = Path(__file__).resolve().parents[1]


def test_subprocess_environment_works_without_windows_only_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux CI can build the minimal subprocess environment without SYSTEMROOT."""
    monkeypatch.delenv("SYSTEMROOT", raising=False)

    environment = command_environment({"NATS_URL": "nats://nats:4222"})

    assert "SYSTEMROOT" not in environment
    assert environment["NATS_URL"] == "nats://nats:4222"


def test_invalid_cli_configuration_exits_safely_without_a_traceback() -> None:
    """A missing setting produces one safe startup error, never a secret-bearing traceback."""
    environment = command_environment(
        {
            "DATABASE_URL": "postgresql://runtime:top-secret@postgres/reposcope",
            "REDIS_URL": "redis://redis:6379/0",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "reposcope", "agent"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "NATS_URL" in result.stderr
    assert "Traceback" not in result.stderr
    assert "top-secret" not in result.stderr
    assert "postgresql://" not in result.stderr


def test_unreachable_runtime_dependencies_exit_safely() -> None:
    """A startup connection failure has the same non-secret process boundary as bad config."""
    environment = command_environment(
        {
            "DATABASE_URL": "postgresql://runtime:top-secret@127.0.0.1:1/reposcope",
            "REDIS_URL": "redis://127.0.0.1:1/0",
            "NATS_URL": "nats://127.0.0.1:1",
            "STARTUP_TIMEOUT_SECONDS": "0.1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "reposcope", "agent"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "startup_failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert "top-secret" not in result.stderr
    assert "postgresql://" not in result.stderr


def test_malformed_url_cannot_leak_a_secret_or_traceback() -> None:
    """URL parser failures are converted to the same safe configuration boundary."""
    environment = command_environment(
        {
            "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
            "REDIS_URL": "redis://redis:6379/0",
            "NATS_URL": "nats://user:fake-secret@bad／host",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "reposcope", "agent"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "startup_configuration_invalid" in result.stderr
    assert "Traceback" not in result.stderr
    assert "fake-secret" not in result.stderr


def command_environment(overrides: dict[str, str]) -> dict[str, str]:
    """Build the smallest portable environment needed by command subprocess tests."""
    environment = {"PYTHONPATH": str(ROOT / "src"), "PATH": os.environ.get("PATH", "")}
    system_root = os.environ.get("SYSTEMROOT")
    if system_root is not None:
        environment["SYSTEMROOT"] = system_root
    environment.update(overrides)
    return environment


def test_cli_argument_selects_the_requested_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command role overrides environment selection before resource startup."""
    captured: list[RuntimeSettings] = []

    async def capture(settings: RuntimeSettings) -> None:
        captured.append(settings)

    monkeypatch.setattr(command, "run_role", capture)
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:secret@postgres/reposcope")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("NATS_URL", "nats://nats:4222")
    monkeypatch.setenv("ROLE", "api")

    assert command.main(("agent",)) == 0
    assert captured[0].role == "agent"
    assert captured[0].database_pool_size == 5
