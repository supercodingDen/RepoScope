"""Real JetStream source-continuation topology compatibility."""

from __future__ import annotations

import pytest

from reposcope.adapters.nats_delivery import JetStreamBroker
from reposcope.domain.delivery import SUBJECTS
from tests.integration.test_delivery import broker
from tests.test_source_event import source_event

__all__ = ["broker"]
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_known_previous_topology_upgrades_and_preserves_consumers(
    broker: JetStreamBroker,
) -> None:
    old = broker.stream_config()
    old.subjects = [broker.subject(subject) for subject in SUBJECTS.values()]
    await broker.js.update_stream(old)
    await broker.setup()
    event = source_event()
    await broker.publish(event)
    stream = await broker.js.stream_info(broker.stream)
    assert stream.state.messages == 1
    assert stream.state.consumer_count == 2
    stored = await broker.js.get_msg(broker.stream, seq=1)
    assert stored.subject == broker.subject("repo.source.acquired")
    assert stored.data == event.model_dump_json().encode()
    assert (await broker.consumer_info("indexer")).num_pending == 0
    assert (await broker.consumer_info("agent")).num_pending == 0


@pytest.mark.asyncio
async def test_previous_topology_with_other_drift_is_not_mutated(
    broker: JetStreamBroker,
) -> None:
    drift = broker.stream_config()
    drift.subjects = [broker.subject(subject) for subject in SUBJECTS.values()]
    drift.max_bytes = 123456
    await broker.js.update_stream(drift)
    with pytest.raises(RuntimeError, match="configuration drift"):
        await broker.setup()
    actual = await broker.js.stream_info(broker.stream)
    assert actual.config.max_bytes == 123456
    assert actual.config.subjects == drift.subjects
