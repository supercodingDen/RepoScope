"""Verify the pinned small-repository demo against fresh disposable Compose volumes."""

from __future__ import annotations

import argparse
import asyncio
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

from scripts.demo import demonstrate
from scripts.smoke_test import SmokeFailure, command, smoke_environment, wait_readiness

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_URL = "https://github.com/pallets/itsdangerous"
COMMIT_SHA = "672971d66a2ef9f85151e53283113f33d642dabd"
QUESTION = "Where is URL-safe signing implemented?"


def verify(port: int) -> None:
    """Run the documented CLI flow on a new project and remove only its volumes."""
    if shutil.which("docker") is None:
        raise SmokeFailure("Docker is required for the disposable demo check")
    environment = smoke_environment(port)
    environment.update(PROVIDER_MODE="mock", ALLOW_PAID_API_CALLS="false", OPENAI_API_KEY="")
    project = f"reposcope-demo-{secrets.token_hex(4)}"
    base = ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "-p", project]
    command(["docker", "info", "--format", "{{.ServerVersion}}"], environment, 30)
    command([*base, "config", "--quiet"], environment)
    try:
        print("Building and starting a fresh mock-only demo stack.", flush=True)
        command([*base, "up", "--build", "--wait", "--wait-timeout", "180"], environment, 900)
        wait_readiness(base, environment, port, 200)

        async def execute() -> str:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
                return await demonstrate(
                    client,
                    REPOSITORY_URL,
                    QUESTION,
                    environment["REPOSCOPE_API_TOKEN"],
                    requested_ref=COMMIT_SHA,
                    timeout_seconds=900,
                )

        answer = asyncio.run(execute())
        if COMMIT_SHA not in answer:
            raise SmokeFailure("The demo did not return a citation to the pinned commit")
        print("PASS: fresh import, mock run, SSE and pinned citation.")
    finally:
        command([*base, "down", "--volumes", "--remove-orphans"], environment)


def main() -> int:
    """Report only safe errors and never print temporary credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18002)
    arguments = parser.parse_args()
    if not 1024 <= arguments.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    try:
        verify(arguments.port)
    except (
        SmokeFailure,
        subprocess.TimeoutExpired,
        httpx.HTTPError,
        RuntimeError,
        ValueError,
    ) as exc:
        message = (
            str(exc) if isinstance(exc, SmokeFailure) else "Demo verification could not finish"
        )
        print(f"FAIL: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
