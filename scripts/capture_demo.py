"""Capture three mock-only cases on disposable Compose volumes, without reading dotenv."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import ValidationError

from contracts.models import (
    JobView,
    RepositoryAccepted,
    RunAccepted,
    RunEvent,
    RunView,
    SearchResponse,
)
from scripts.demo_recording import (
    COMMIT_SHA,
    REPOSITORY_URL,
    DemoCase,
    DemoRecording,
    ExcerptManifest,
    excerpt_key,
    normalized_excerpt,
    write_recording,
)
from scripts.smoke_test import SmokeFailure, command, smoke_environment, wait_readiness

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CapturedStream:
    events: list[RunEvent]
    last_cursor: str | None


async def read_events(
    client: httpx.AsyncClient, run_id: str, *, cursor: str | None = None, limit: int = 32
) -> CapturedStream:
    """Read an actual SSE connection, optionally closing it before completion."""
    headers = {"Accept": "text/event-stream"}
    after = 0
    if cursor is not None:
        if not cursor.startswith(run_id + ":") or not cursor.rsplit(":", 1)[1].isdigit():
            raise ValueError("Invalid capture cursor")
        after = int(cursor.rsplit(":", 1)[1])
        headers["Last-Event-ID"] = cursor
    events: list[RunEvent] = []
    wire_id = ""
    wire_kind = ""
    payload = ""
    last_received: str | None = None
    async with client.stream("GET", f"/v1/runs/{run_id}/events", headers=headers) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("id: "):
                wire_id = line[4:]
            elif line.startswith("event: "):
                wire_kind = line[7:]
            elif line.startswith("data: "):
                payload += line[6:]
            elif line == "" and payload:
                event = RunEvent.model_validate_json(payload)
                if str(event.run_id) != run_id or event.sequence != after + len(events) + 1:
                    raise ValueError("Foreign, duplicated, or skipped event in capture")
                if wire_id != f"{event.run_id}:{event.sequence}" or wire_kind != event.data.kind:
                    raise ValueError("SSE wire cursor or event name does not match its payload")
                events.append(event)
                last_received = wire_id
                wire_id, wire_kind, payload = "", "", ""
                if len(events) == limit:
                    break
    if payload:
        raise ValueError("Incomplete SSE frame")
    return CapturedStream(events, last_received)


async def capture_cases(client: httpx.AsyncClient, application_commit: str) -> DemoRecording:
    response = await client.post(
        "/v1/repositories",
        headers={"Idempotency-Key": str(uuid4())},
        json={"url": REPOSITORY_URL, "requested_ref": COMMIT_SHA},
    )
    response.raise_for_status()
    print("Import accepted; validating HTTP contract.", flush=True)
    accepted = RepositoryAccepted.model_validate_json(response.content)
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        response = await client.get(f"/v1/jobs/{accepted.job_id}")
        response.raise_for_status()
        job = JobView.model_validate_json(response.content)
        if job.status == "succeeded":
            break
        if job.status == "failed":
            raise ValueError("Disposable import failed")
        await asyncio.sleep(1)
    else:
        raise TimeoutError("Disposable import deadline exceeded")
    print("Pinned source imported; recording search and event streams.", flush=True)
    cases: list[DemoCase] = []
    for case_id, title, question in (
        ("lookup", "Find an implementation", "unsign"),
        ("scoped", "Focus the search", "unsign"),
        ("resume", "Resume a disconnected stream", "unsign"),
    ):
        response = await client.post(
            "/v1/runs",
            headers={"Idempotency-Key": str(uuid4())},
            json={"repository_id": str(accepted.repository_id), "question": question},
        )
        response.raise_for_status()
        run = RunAccepted.model_validate_json(response.content)
        run_id = str(run.run_id)
        stream = await read_events(client, run_id, limit=2 if case_id == "resume" else 32)
        first = stream.events
        resumed = (
            (await read_events(client, run_id, cursor=stream.last_cursor)).events
            if case_id == "resume"
            else []
        )
        response = await client.get(f"/v1/runs/{run_id}")
        response.raise_for_status()
        completed = RunView.model_validate_json(response.content)
        if completed.result is None or not completed.result.citations:
            raise ValueError("Demo requires a successful cited mock result")
        prefix = completed.result.citations[0].path if case_id == "scoped" else None
        response = await client.post(
            "/v1/search",
            json={
                "repository_id": str(accepted.repository_id),
                "query": question,
                "top_k": 12,
                "path_prefix": prefix,
            },
        )
        response.raise_for_status()
        search = SearchResponse.model_validate_json(response.content)
        case = DemoCase.model_validate_json(
            json.dumps(
                {
                    "id": case_id,
                    "title": title,
                    "question": question,
                    "path_prefix": prefix,
                    "search": search.model_dump(mode="json"),
                    "result": completed.result.model_dump(mode="json"),
                    "events": [event.model_dump(mode="json") for event in first + resumed],
                    "resume_after": 2 if case_id == "resume" else None,
                    "resumed_sequences": [event.sequence for event in resumed],
                }
            )
        )
        cases.append(case)
        print(
            f"Captured {case_id}: {len(case.events)} events; pinned citation verified.", flush=True
        )
    return DemoRecording.model_validate_json(
        json.dumps(
            {
                "schema_version": 1,
                "recorded_at": datetime.now(UTC).isoformat(),
                "application_commit": application_commit,
                "repository_url": REPOSITORY_URL,
                "commit_sha": COMMIT_SHA,
                "provider_mode": "mock",
                "cases": [case.model_dump(mode="json") for case in cases],
            }
        )
    )


def archive_source(repository: Path, commit: str, target: Path) -> None:
    """Build exactly the selected Git object, irrespective of local working changes."""
    if re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise ValueError("An immutable application commit is required")
    result = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=repository,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise ValueError("Cannot archive the reviewed application commit")
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(target, filter="data")


async def approve_excerpts(recording: DemoRecording) -> ExcerptManifest:
    """Independently compare every exported excerpt with fixed upstream source bytes."""
    files: dict[str, list[str]] = {}
    digests: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as source_client:
        for case in recording.cases:
            for match in case.search.results:
                if match.path not in files:
                    response = await source_client.get(
                        f"https://raw.githubusercontent.com/pallets/itsdangerous/{COMMIT_SHA}/"
                        + quote(match.path, safe="/")
                    )
                    response.raise_for_status()
                    if len(response.content) > 1_048_576:
                        raise ValueError("Upstream verification file exceeds source bound")
                    files[match.path] = response.content.decode("utf-8").splitlines()
                excerpt = normalized_excerpt(match.content)
                upstream = "\n".join(files[match.path][match.start_line - 1 : match.end_line])
                if excerpt not in upstream:
                    raise ValueError("Recorded excerpt does not occur in the pinned upstream span")
                digests[excerpt_key(match.path, match.start_line, match.end_line)] = hashlib.sha256(
                    excerpt.encode("utf-8")
                ).hexdigest()
    return ExcerptManifest(commit_sha=COMMIT_SHA, excerpts=digests)


def capture(stack_root: Path, application_commit: str, target: Path, port: int) -> None:
    environment = smoke_environment(port)
    environment.update(PROVIDER_MODE="mock", ALLOW_PAID_API_CALLS="false", OPENAI_API_KEY="")
    project = f"reposcope-recording-{uuid4().hex[:8]}"
    base = ["docker", "compose", "-f", str(stack_root / "compose.yaml"), "-p", project]
    command([*base, "config", "--quiet"], environment)
    try:
        print("Building a disposable mock-only recording stack.", flush=True)
        command([*base, "up", "--build", "--wait", "--wait-timeout", "180"], environment, 1200)
        wait_readiness(base, environment, port, 200)
        print("Recording stack ready.", flush=True)

        async def execute() -> DemoRecording:
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}",
                timeout=150,
                headers={"Authorization": f"Bearer {environment['REPOSCOPE_API_TOKEN']}"},
            ) as client:
                return await capture_cases(client, application_commit)

        recording = asyncio.run(execute())
        manifest = asyncio.run(approve_excerpts(recording))
        write_recording(recording, target, manifest=manifest)
        (target.parent / "approved-excerpts.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print("PASS: public recording validated and written; no paid calls.", flush=True)
    finally:
        command([*base, "down", "--volumes", "--remove-orphans"], environment, 120)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-commit", required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "web/demo/public/recordings/demo.json"
    )
    parser.add_argument("--port", type=int, default=18003)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    try:
        with tempfile.TemporaryDirectory(prefix="reposcope-reviewed-recording-") as temporary:
            stack_root = Path(temporary).resolve()
            if stack_root.parent != Path(tempfile.gettempdir()).resolve():
                raise ValueError("Unexpected temporary build directory")
            archive_source(ROOT, args.application_commit, stack_root)
            capture(stack_root, args.application_commit, args.output, args.port)
    except (
        ValueError,
        TimeoutError,
        OSError,
        httpx.HTTPError,
        SmokeFailure,
        subprocess.TimeoutExpired,
    ) as exc:
        print(
            f"Capture failed ({type(exc).__name__}); no response bodies printed.", file=sys.stderr
        )
        if isinstance(exc, ValidationError):
            print(
                "Invalid fields: "
                + ", ".join(
                    ".".join(str(part) for part in error["loc"])
                    for error in exc.errors(include_input=False, include_context=False)
                ),
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
