"""Source continuation is publishable and becomes a T06 consumer event."""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.examples import EVENT, GEN, JOB, PRINCIPAL, REPO, SHA, TIME, TRACE
from contracts.models import SourceAcquired
from reposcope.domain.delivery import parse_event, parse_publication


def source_event() -> SourceAcquired:
    return SourceAcquired.model_validate_json(
        json.dumps(
            {
                "event_id": EVENT,
                "aggregate_id": JOB,
                "trace_id": TRACE,
                "occurred_at": TIME,
                "payload": {
                    "job_id": JOB,
                    "repository_id": REPO,
                    "generation_id": GEN,
                    "principal_id": PRINCIPAL,
                    "commit_sha": SHA,
                    "manifest_digest": "a" * 64,
                },
            }
        )
    )


def test_source_event_is_publishable_and_consumable() -> None:
    event = source_event()
    assert parse_publication(event.model_dump_json()) == event
    assert parse_event(event.model_dump_json()) == event


@pytest.mark.parametrize(
    "field,value",
    [
        ("commit_sha", "HEAD"),
        ("manifest_digest", "../source"),
        ("source", "secret file contents"),
    ],
)
def test_source_event_rejects_unpinned_or_extra_content(field: str, value: str) -> None:
    raw = source_event().model_dump()
    raw["payload"][field] = value
    with pytest.raises(ValidationError):
        SourceAcquired.model_validate(raw)


def test_source_event_requires_job_aggregate() -> None:
    raw = source_event().model_dump()
    raw["aggregate_id"] = UUID(GEN)
    with pytest.raises(ValidationError):
        SourceAcquired.model_validate(raw)
