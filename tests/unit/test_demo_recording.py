"""Public recordings reject mismatched evidence and accidental secret exports."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import ValidationError

from scripts.demo_recording import COMMIT_SHA, ExcerptManifest, validate_recording, write_recording


def example_recording() -> dict[str, object]:
    citation: dict[str, object] = {
        "chunk_id": "00000000-0000-0000-0000-000000000004",
        "repository_id": "00000000-0000-0000-0000-000000000001",
        "generation_id": "00000000-0000-0000-0000-000000000002",
        "commit_sha": "672971d66a2ef9f85151e53283113f33d642dabd",
        "path": "src/itsdangerous/url_safe.py",
        "start_line": 1,
        "end_line": 2,
    }
    result = {
        "answer": "Relevant source: src/itsdangerous/url_safe.py:1-2. class Example:\n    pass",
        "citations": [citation],
        "evidence_status": "supported",
        "model": "mock",
        "estimated_cost_usd": "0.000000",
    }
    run = "00000000-0000-0000-0000-000000000003"
    events = [
        {
            "run_id": run,
            "sequence": 1,
            "occurred_at": "2026-11-17T12:00:00Z",
            "data": {"kind": "run.started", "model": "mock"},
        },
        {
            "run_id": run,
            "sequence": 2,
            "occurred_at": "2026-11-17T12:00:01Z",
            "data": {"kind": "tool.started", "tool": "search_code", "step": 1},
        },
        {
            "run_id": run,
            "sequence": 3,
            "occurred_at": "2026-11-17T12:00:02Z",
            "data": {"kind": "tool.completed", "tool": "search_code", "step": 1},
        },
        {
            "run_id": run,
            "sequence": 4,
            "occurred_at": "2026-11-17T12:00:03Z",
            "data": {"kind": "run.completed", "result": result},
        },
    ]
    case = {
        "id": "lookup",
        "title": "Find an implementation",
        "question": "URLSafeSerializer",
        "path_prefix": None,
        "search": {
            "repository_id": citation["repository_id"],
            "generation_id": citation["generation_id"],
            "commit_sha": citation["commit_sha"],
            "duration_ms": 12.5,
            "results": [{**citation, "score": 0.02, "content": "class Example:\n    pass"}],
        },
        "result": result,
        "events": events,
        "resume_after": None,
        "resumed_sequences": [],
    }
    scoped = {**copy.deepcopy(case), "id": "scoped", "path_prefix": citation["path"]}
    resumed = {
        **copy.deepcopy(case),
        "id": "resume",
        "resume_after": 2,
        "resumed_sequences": [3, 4],
    }
    return {
        "schema_version": 1,
        "recorded_at": "2026-11-17T12:00:05Z",
        "application_commit": "a856be4e0db793d6118391d65b2236e853ff3c62",
        "repository_url": "https://github.com/pallets/itsdangerous",
        "commit_sha": citation["commit_sha"],
        "provider_mode": "mock",
        "cases": [case, scoped, resumed],
    }


def test_recording_roundtrip_emits_only_validated_fields(tmp_path: Path) -> None:
    manifest = ExcerptManifest(
        commit_sha=COMMIT_SHA,
        excerpts={
            "src/itsdangerous/url_safe.py:1:2": hashlib.sha256(
                b"class Example:\n    pass"
            ).hexdigest()
        },
    )
    recording = validate_recording(json.dumps(example_recording()), manifest=manifest)
    target = tmp_path / "demo.json"
    write_recording(recording, target, manifest=manifest)
    assert validate_recording(target.read_text(encoding="utf-8"), manifest=manifest) == recording
    assert recording.cases[2].resumed_sequences == [3, 4]


@pytest.mark.parametrize("field", ["authorization", "environment", "database_url"])
def test_recording_rejects_unknown_export_fields(field: str) -> None:
    payload = example_recording()
    payload[field] = "must not be exported"
    with pytest.raises(ValidationError):
        validate_recording(json.dumps(payload))


@pytest.mark.parametrize(
    "old,new",
    [
        ("672971d66a2ef9f85151e53283113f33d642dabd", "a" * 40),
        ("https://github.com/pallets/itsdangerous", "https://github.com/other/private"),
        ('"resumed_sequences": [3, 4]', '"resumed_sequences": [2, 3, 4]'),
        ('"sequence": 2', '"sequence": 3'),
        ('"end_line": 2', '"end_line": 200'),
        ('"model": "mock"', '"model": "gpt-5.6-luna"'),
    ],
)
def test_recording_rejects_unverifiable_provenance(old: str, new: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        validate_recording(json.dumps(example_recording()).replace(old, new))


@pytest.mark.parametrize(
    "sensitive",
    [
        "-----BEGIN PRIVATE KEY-----",
        "ghp_" + "a" * 36,
        "sk-proj-" + "a" * 40,
        "C:\\Users\\someone\\private",
    ],
)
def test_recording_rejects_sensitive_content(sensitive: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        validate_recording(
            json.dumps(example_recording()).replace(
                "Relevant source: src/itsdangerous/url_safe.py:1-2.",
                json.dumps(sensitive)[1:-1],
            )
        )


def test_checked_in_recording_has_three_verified_cases() -> None:
    root = Path(__file__).resolve().parents[2]
    recording = validate_recording(
        (root / "web/demo/public/recordings/demo.json").read_text(encoding="utf-8")
    )
    assert {case.id for case in recording.cases} == {"lookup", "scoped", "resume"}
    scoped = next(case for case in recording.cases if case.id == "scoped")
    assert scoped.path_prefix is not None
    resumed = next(case for case in recording.cases if case.id == "resume")
    assert resumed.resume_after == 2
    assert resumed.resumed_sequences == [3, 4]


@pytest.mark.asyncio
async def test_capture_resume_reads_only_events_after_cursor() -> None:
    from scripts.capture_demo import read_events

    run_id = "00000000-0000-0000-0000-000000000003"

    def serve(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Last-Event-ID") != f"{run_id}:1":
            return httpx.Response(400)
        event = {
            "run_id": run_id,
            "sequence": 2,
            "occurred_at": "2026-11-17T12:00:01Z",
            "data": {"kind": "tool.started", "tool": "search_code", "step": 1},
        }
        return httpx.Response(
            200, text=f"id: {run_id}:2\nevent: tool.started\ndata: {json.dumps(event)}\n\n"
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(serve), base_url="http://127.0.0.1:18003"
    ) as client:
        result = await read_events(client, run_id, cursor=f"{run_id}:1")
    assert [event.sequence for event in result.events] == [2]
    assert result.last_cursor == f"{run_id}:2"


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_lines",
        "duplicate_id",
        "live_start",
        "second_start",
        "missing_resume",
        "missing_case",
        "changed_source",
        "bearer",
    ],
)
def test_public_export_rejects_review_regressions(mutation: str) -> None:
    source = Path(__file__).resolve().parents[2] / "web/demo/public/recordings/demo.json"
    payload = cast(dict[str, object], json.loads(source.read_text(encoding="utf-8")))
    cases = cast(list[dict[str, object]], payload["cases"])
    case = cases[0]
    search = cast(dict[str, object], case["search"])
    matches = cast(list[dict[str, object]], search["results"])
    events = cast(list[dict[str, object]], case["events"])
    if mutation == "extra_lines":
        matches[0]["content"] = str(matches[0]["content"]) + "\nunverified extra line"
    elif mutation == "duplicate_id":
        matches.insert(0, {**matches[0], "path": "other.py"})
    elif mutation == "live_start":
        cast(dict[str, object], events[0]["data"])["model"] = "gpt-5.6-luna"
    elif mutation == "second_start":
        events[1]["data"] = {"kind": "run.started", "model": "mock"}
    elif mutation == "missing_resume":
        cases[2]["resume_after"] = None
        cases[2]["resumed_sequences"] = []
    elif mutation == "missing_case":
        cases.pop()
    elif mutation == "changed_source":
        original = str(matches[-1]["content"])
        matches[-1]["content"] = "!" + original[1:]
    else:
        cast(dict[str, object], case["result"])["answer"] = (
            "Authorization: Bearer synthetic-private-value"
        )
        cast(dict[str, object], events[-1]["data"])["result"] = case["result"]
    with pytest.raises((ValidationError, ValueError)):
        validate_recording(json.dumps(payload))


@pytest.mark.parametrize("wire_id", ["", "foreign:2", "00000000-0000-0000-0000-000000000003:3"])
@pytest.mark.asyncio
async def test_capture_rejects_missing_or_wrong_wire_cursor(wire_id: str) -> None:
    from scripts.capture_demo import read_events

    run_id = "00000000-0000-0000-0000-000000000003"
    event = {
        "run_id": run_id,
        "sequence": 2,
        "occurred_at": "2026-11-17T12:00:01Z",
        "data": {"kind": "tool.started", "tool": "search_code", "step": 1},
    }

    def serve(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=f"id: {wire_id}\nevent: tool.started\ndata: {json.dumps(event)}\n\n"
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(serve), base_url="http://127.0.0.1:18003"
    ) as client:
        with pytest.raises(ValueError):
            await read_events(client, run_id, cursor=f"{run_id}:1")


def test_capture_builds_the_selected_commit_not_modified_worktree(tmp_path: Path) -> None:
    from scripts.capture_demo import archive_source

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    git("init")
    (repo / "example.py").write_text("approved", encoding="utf-8")
    git("add", "example.py")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    commit = git("rev-parse", "HEAD")
    (repo / "example.py").write_text("modified", encoding="utf-8")
    output = tmp_path / "build"
    archive_source(repo, commit, output)
    assert (output / "example.py").read_text(encoding="utf-8") == "approved"
