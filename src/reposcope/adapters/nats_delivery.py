"""Bounded file-backed JetStream topology; never mutate unrelated resources."""

from __future__ import annotations

import re
from typing import cast

from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.errors import TimeoutError as NatsTimeout
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    ConsumerInfo,
    DeliverPolicy,
    DiscardPolicy,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.client import JetStreamContext
from nats.js.errors import APIError, NotFoundError

from reposcope.domain.delivery import (
    PUBLICATION_SUBJECTS,
    SUBJECTS,
    DeliveryPolicy,
    PublicationEvent,
)


class JetStreamBroker:
    def __init__(
        self, client: Client, policy: DeliveryPolicy | None = None, namespace: str = ""
    ) -> None:
        if namespace and re.fullmatch(r"[A-Za-z0-9_]{1,64}", namespace) is None:
            raise ValueError("Invalid broker namespace")
        self.client = client
        self.policy = policy or DeliveryPolicy()
        self.namespace = namespace
        self.stream = (namespace + "_" if namespace else "") + "REPOSCOPE_WORK_V1"
        self.js = client.jetstream()
        self.subscriptions: dict[str, JetStreamContext.PullSubscription] = {}

    def subject(self, event_type: str) -> str:
        return (self.namespace + "." if self.namespace else "") + event_type

    def stream_config(self) -> StreamConfig:
        return StreamConfig(
            name=self.stream,
            subjects=[self.subject(subject) for subject in PUBLICATION_SUBJECTS],
            retention=RetentionPolicy.LIMITS,
            storage=StorageType.FILE,
            max_consumers=2,
            max_msgs=100000,
            max_bytes=64 * 1024 * 1024,
            max_age=86400,
            max_msg_size=65536,
            discard=DiscardPolicy.NEW,
            num_replicas=1,
            duplicate_window=120,
        )

    def consumer_config(self, consumer: str) -> ConsumerConfig:
        return ConsumerConfig(
            durable_name=consumer,
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=60,
            max_deliver=self.policy.max_deliver,
            filter_subject=self.subject(SUBJECTS[consumer]),
            max_ack_pending=2,
            max_waiting=2,
        )

    async def setup(self) -> None:
        wanted = self.stream_config()
        try:
            stream = await self.js.stream_info(self.stream)
        except NotFoundError:
            try:
                stream = await self.js.add_stream(wanted)
            except APIError:
                stream = await self.js.stream_info(self.stream)
        fields: tuple[str, ...] = (
            "subjects",
            "retention",
            "storage",
            "max_consumers",
            "max_msgs",
            "max_bytes",
            "max_age",
            "max_msg_size",
            "discard",
            "num_replicas",
            "duplicate_window",
        )
        previous_subjects = [self.subject(subject) for subject in SUBJECTS.values()]
        if stream.config.subjects == previous_subjects and all(
            getattr(stream.config, key) == getattr(wanted, key)
            for key in fields
            if key != "subjects"
        ):
            # Only the exact T04 topology is eligible for this additive upgrade.
            upgraded = stream.config
            upgraded.subjects = wanted.subjects
            stream = await self.js.update_stream(upgraded)
        if any(getattr(stream.config, key) != getattr(wanted, key) for key in fields):
            raise RuntimeError("Delivery stream configuration drift")
        for consumer in SUBJECTS:
            expected = self.consumer_config(consumer)
            try:
                actual = await self.js.consumer_info(self.stream, consumer)
            except NotFoundError:
                try:
                    actual = await self.js.add_consumer(self.stream, expected)
                except APIError:
                    actual = await self.js.consumer_info(self.stream, consumer)
            fields = (
                "durable_name",
                "deliver_policy",
                "ack_policy",
                "ack_wait",
                "max_deliver",
                "filter_subject",
                "max_ack_pending",
                "max_waiting",
            )
            if any(getattr(actual.config, key) != getattr(expected, key) for key in fields):
                raise RuntimeError("Delivery consumer configuration drift")
            self.subscriptions[consumer] = await self.js.pull_subscribe_bind(
                durable=consumer, stream=self.stream
            )

    async def publish(self, event: PublicationEvent) -> None:
        acknowledgment = await self.js.publish(
            self.subject(event.event_type),
            event.model_dump_json().encode(),
            headers={"Nats-Msg-Id": str(event.event_id)},
            timeout=5,
        )
        if acknowledgment.stream != self.stream:
            raise RuntimeError("Unexpected publication acknowledgment")

    async def fetch_one(self, consumer: str) -> Msg | None:
        try:
            messages = await self.subscriptions[consumer].fetch(batch=1, timeout=1)
        except (NatsTimeout, TimeoutError):
            return None
        return messages[0] if messages else None

    async def consumer_info(self, consumer: str) -> ConsumerInfo:
        return cast(ConsumerInfo, await self.js.consumer_info(self.stream, consumer))

    async def flush(self) -> None:
        await self.client.flush()
