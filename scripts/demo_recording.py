"""Allowlisted public recording format, separate from operational logs and credentials."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from contracts.models import CommitSHA, Contract, RunEvent, RunResult, SearchResponse

REPOSITORY_URL = "https://github.com/pallets/itsdangerous"
COMMIT_SHA: Final = "672971d66a2ef9f85151e53283113f33d642dabd"
SENSITIVE = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b|"
    r"Authorization\s*:\s*Bearer\s+\S+|"
    r"[A-Za-z]:\\\\(?:Users|home)\\\\",
    re.IGNORECASE,
)
MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "web/demo/public/recordings/approved-excerpts.json"
)


def normalized_excerpt(content: str) -> str:
    return content.removesuffix("\n")


def excerpt_key(path: str, start: int, end: int) -> str:
    return f"{path}:{start}:{end}"


class ExcerptManifest(Contract):
    commit_sha: Literal["672971d66a2ef9f85151e53283113f33d642dabd"]
    excerpts: dict[str, Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]]


class DemoCase(Contract):
    id: Literal["lookup", "scoped", "resume"]
    title: Annotated[str, Field(min_length=1, max_length=100)]
    question: Annotated[str, Field(min_length=1, max_length=200)]
    path_prefix: str | None
    search: SearchResponse
    result: RunResult
    events: Annotated[list[RunEvent], Field(min_length=2, max_length=32)]
    resume_after: Annotated[int, Field(ge=1)] | None
    resumed_sequences: list[int]

    @model_validator(mode="after")
    def verify_evidence(self) -> Self:
        if self.search.commit_sha != COMMIT_SHA or self.result.model != "mock":
            raise ValueError("This recording format requires the pinned mock-only demo")
        if self.result.estimated_cost_usd != "0.000000":
            raise ValueError("Mock recordings cannot contain paid usage")
        available = {item.chunk_id: item for item in self.search.results}
        if len(available) != len(self.search.results):
            raise ValueError("Duplicate evidence identifiers")
        for item in self.search.results:
            if item.end_line - item.start_line + 1 != len(
                normalized_excerpt(item.content).split("\n")
            ):
                raise ValueError("Source excerpt does not cover the claimed line span")
            if self.path_prefix and not (
                item.path == self.path_prefix or item.path.startswith(self.path_prefix + "/")
            ):
                raise ValueError("Scoped results escaped the recorded filter")
        for citation in self.result.citations:
            match = available.get(citation.chunk_id)
            if (
                match is None
                or match.model_dump(exclude={"score", "content"}) != citation.model_dump()
            ):
                raise ValueError("Result citation has no matching recorded source evidence")
        if len(self.result.citations) != 1:
            raise ValueError("This mock demo requires exactly one citation")
        cited = available[self.result.citations[0].chunk_id]
        expected_answer = (
            f"Relevant source: {cited.path}:{cited.start_line}-{cited.end_line}. "
            f"{cited.content[:1000]}"
        )
        if self.result.answer != expected_answer:
            raise ValueError("Mock answer does not match its cited excerpt")
        first_run = self.events[0].run_id
        for index, event in enumerate(self.events, 1):
            if event.sequence != index or event.run_id != first_run:
                raise ValueError("Events must be contiguous and belong to one run")
            if index > 1 and event.occurred_at < self.events[index - 2].occurred_at:
                raise ValueError("Event timestamps moved backward")
        started = self.events[0].data
        if started.kind != "run.started" or started.model != "mock":
            raise ValueError("Missing run start")
        if any(e.data.kind == "run.started" for e in self.events[1:]):
            raise ValueError("Duplicate run start")
        terminal = self.events[-1].data
        if terminal.kind != "run.completed" or terminal.result != self.result:
            raise ValueError("Final event does not match the recorded result")
        if any(e.data.kind in {"run.completed", "run.failed"} for e in self.events[:-1]):
            raise ValueError("Events continued after completion")
        expected = (
            list(range(self.resume_after + 1, len(self.events) + 1))
            if self.resume_after is not None
            else []
        )
        if self.resume_after is not None and self.resume_after >= len(self.events):
            raise ValueError("Resume cursor must precede completion")
        if self.resumed_sequences != expected:
            raise ValueError("Resume proof repeats or skips events")
        if (self.id == "resume") != (self.resume_after == 2):
            raise ValueError("Reconnect proof is required only for the resume case")
        if (self.id == "scoped") != (self.path_prefix is not None):
            raise ValueError("Only the scoped search may specify a filter")
        return self


class DemoRecording(Contract):
    schema_version: Literal[1]
    recorded_at: AwareDatetime
    application_commit: CommitSHA
    repository_url: Literal["https://github.com/pallets/itsdangerous"]
    commit_sha: Literal["672971d66a2ef9f85151e53283113f33d642dabd"]
    provider_mode: Literal["mock"]
    cases: Annotated[list[DemoCase], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({item.id for item in self.cases}) != len(self.cases):
            raise ValueError("Case identifiers must be unique")
        return self


def validate_recording(payload: str, *, manifest: ExcerptManifest | None = None) -> DemoRecording:
    """Validate JSON without echoing potentially sensitive input in CLI diagnostics."""
    if len(payload) > 500_000 or SENSITIVE.search(
        json.dumps(json.loads(payload), ensure_ascii=False)
    ):
        raise ValueError("Recording exceeded its public export boundary")
    recording = DemoRecording.model_validate_json(payload)
    approved = manifest or ExcerptManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )
    for case in recording.cases:
        for match in case.search.results:
            key = excerpt_key(match.path, match.start_line, match.end_line)
            digest = hashlib.sha256(normalized_excerpt(match.content).encode("utf-8")).hexdigest()
            if approved.excerpts.get(key) != digest:
                raise ValueError(
                    "Excerpt does not match the independently approved source manifest"
                )
    return recording


def write_recording(
    recording: DemoRecording, target: Path, *, manifest: ExcerptManifest | None = None
) -> None:
    """Write only the validated format, never raw HTTP responses or headers."""
    payload = recording.model_dump_json(indent=2) + "\n"
    validate_recording(payload, manifest=manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8", newline="\n")
