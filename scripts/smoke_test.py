"""Exercise the skeleton on a disposable Compose project with zero provider calls."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ROLES = ("api", "indexer", "agent")


class SmokeFailure(Exception):
    """A safe smoke-test failure without captured connection strings."""


def smoke_environment(port: int) -> dict[str, str]:
    """Return an isolated Compose environment while retaining non-Compose host settings."""
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("COMPOSE_")
    }
    environment.update(
        COMPOSE_DISABLE_ENV_FILE="1",
        POSTGRES_PASSWORD=secrets.token_hex(24),
        APP_DATABASE_PASSWORD=secrets.token_hex(24),
        API_PORT=str(port),
        REPOSCOPE_API_TOKEN=secrets.token_hex(24),
        REPOSCOPE_PRINCIPAL_ID="00000000-0000-0000-0000-000000000001",
    )
    return environment


def command(args: list[str], environment: dict[str, str], timeout: float = 180) -> str:
    """Run a bounded command; never echo captured potentially sensitive stderr."""
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise SmokeFailure(f"Command failed with exit code {result.returncode}: {args[0]}")
    return result.stdout


def public_status(port: int, path: str) -> int:
    """Return the actual HTTP status, distinguishing unavailable sockets."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/{path}", timeout=4) as response:
            return int(response.status)
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, OSError):
        return 0


def role_status(base: list[str], environment: dict[str, str], role: str) -> int:
    """Probe each private management endpoint from within its container."""
    code = (
        "import urllib.request, urllib.error\n"
        "try:\n"
        " r=urllib.request.urlopen('http://127.0.0.1:9000/readyz',timeout=4)\n"
        " print(r.status); r.close()\n"
        "except urllib.error.HTTPError as e: print(e.code)\n"
        "except (urllib.error.URLError, TimeoutError, OSError): print(0)\n"
    )
    result = command([*base, "exec", "-T", role, "python", "-c", code], environment, 15)
    return int(result.strip())


def wait_readiness(base: list[str], environment: dict[str, str], port: int, expected: int) -> None:
    """Require all roles to observe the same dependency state within a deadline."""
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        statuses = [public_status(port, "readyz")]
        statuses.extend(role_status(base, environment, role) for role in ROLES)
        if all(status == expected for status in statuses):
            return
        time.sleep(1)
    raise SmokeFailure(f"All roles did not reach readiness HTTP {expected}")


def check_business_api(port: int, token: str) -> None:
    """Verify authenticated admission, replay, conflict and status over real HTTP."""
    from contracts.models import JobView, RepositoryAccepted

    base = f"http://127.0.0.1:{port}"
    if public_status(port, "v1/jobs/00000000-0000-0000-0000-000000000001") != 401:
        raise SmokeFailure("Business authentication contract failed")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": secrets.token_hex(16),
    }
    payload = json.dumps({"url": "https://github.com/example/smoke"}).encode()
    request = Request(f"{base}/v1/repositories", data=payload, headers=headers, method="POST")
    with urlopen(request, timeout=15) as response:
        if response.status != 202:
            raise SmokeFailure("Repository admission did not return HTTP 202")
        accepted = RepositoryAccepted.model_validate_json(response.read())
    with urlopen(request, timeout=15) as response:
        if (
            response.status != 202
            or RepositoryAccepted.model_validate_json(response.read()) != accepted
        ):
            raise SmokeFailure("Idempotent replay changed the accepted result")
    status_request = Request(f"{base}/v1/jobs/{accepted.job_id}", headers=headers)
    with urlopen(status_request, timeout=15) as response:
        job = JobView.model_validate_json(response.read())
        if job.job_id != accepted.job_id or job.repository_id != accepted.repository_id:
            raise SmokeFailure("Persisted job status contract failed")
    conflict = Request(
        f"{base}/v1/repositories",
        data=json.dumps({"url": "https://github.com/example/different"}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(conflict, timeout=15):
            raise SmokeFailure("Conflicting idempotency key was accepted")
    except HTTPError as exc:
        if exc.code != 409:
            raise SmokeFailure("Conflicting idempotency key did not return HTTP 409") from None


def run(port: int) -> None:
    """Create, verify and remove only this invocation's unique Compose resources."""
    if shutil.which("docker") is None:
        raise SmokeFailure("Docker is required; install and start Docker Desktop or Docker Engine")
    environment = smoke_environment(port)
    project = f"reposcope-smoke-{secrets.token_hex(4)}"
    base = ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "-p", project]
    command(["docker", "info", "--format", "{{.ServerVersion}}"], environment, 30)
    command([*base, "config", "--quiet"], environment)
    try:
        print("Building and starting an isolated mock-only stack.", flush=True)
        command([*base, "up", "--build", "--wait", "--wait-timeout", "180"], environment, 900)
        wait_readiness(base, environment, port, 200)
        if public_status(port, "healthz") != 200 or public_status(port, "metrics") != 404:
            raise SmokeFailure("Public health/management isolation contract failed")
        command([*base, "run", "--rm", "--no-deps", "migrate"], environment)
        # Destructive database fixtures run with application workers stopped.
        command([*base, "stop", "-t", "20", *ROLES], environment)
        command(
            [*base, "--profile", "test", "run", "--build", "--rm", "--no-deps", "integration"],
            environment,
            900,
        )
        command([*base, "start", *ROLES], environment)
        wait_readiness(base, environment, port, 200)
        check_business_api(port, environment["REPOSCOPE_API_TOKEN"])
        for dependency in ("postgres", "redis", "nats"):
            print(f"Checking {dependency} loss and recovery.", flush=True)
            command([*base, "stop", "-t", "5", dependency], environment)
            wait_readiness(base, environment, port, 503)
            if public_status(port, "healthz") != 200:
                raise SmokeFailure("Dependency loss incorrectly disabled process liveness")
            command([*base, "start", dependency], environment)
            wait_readiness(base, environment, port, 200)
        command([*base, "stop", "-t", "20", *ROLES], environment)
        for role in ROLES:
            container = command([*base, "ps", "-a", "-q", role], environment).strip()
            state = command(
                ["docker", "inspect", "--format", "{{json .State}}", container], environment
            )
            record: object = json.loads(state)
            if not isinstance(record, dict) or record.get("ExitCode") != 0:
                raise SmokeFailure(f"{role} did not shut down gracefully")
        print("PASS: startup, migration, business API, recovery, isolation and shutdown.")
    finally:
        command([*base, "down", "--volumes", "--remove-orphans"], environment)


def main() -> int:
    """Return a safe English failure without credential-bearing command output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18000)
    arguments = parser.parse_args()
    if not 1024 <= arguments.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    try:
        run(arguments.port)
    except (SmokeFailure, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, SmokeFailure) else "Smoke test could not finish"
        print(f"FAIL: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
