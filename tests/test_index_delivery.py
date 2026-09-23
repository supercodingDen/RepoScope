"""T06 source continuations use a durable, separately bounded consumer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from nats.aio.client import Client

from contracts.models import SourceAcquired, SourceAcquiredPayload
from reposcope.adapters.nats_delivery import JetStreamBroker
from reposcope.domain.delivery import SUBJECTS, parse_event


def test_source_continuation_is_a_consumer_event() -> None:
    job_id = uuid4()
    event = SourceAcquired(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        aggregate_id=job_id,
        trace_id=uuid4(),
        payload=SourceAcquiredPayload(
            job_id=job_id,
            repository_id=uuid4(),
            generation_id=uuid4(),
            principal_id=uuid4(),
            commit_sha="a" * 40,
            manifest_digest="b" * 64,
        ),
    )

    assert parse_event(event.model_dump_json()) == event
    assert SUBJECTS["source"] == "repo.source.acquired"


def test_broker_reserves_a_third_bounded_consumer_for_indexing() -> None:
    broker = JetStreamBroker(Client())
    assert broker.stream_config().max_consumers == 3
    assert broker.consumer_config("source").filter_subject == "repo.source.acquired"
