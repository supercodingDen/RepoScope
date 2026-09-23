"""Broker-independent delivery identities, outcomes, and bounded policy."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from contracts.models import AgentRequested, IngestRequested, RunResult, SourceAcquired

type DeliveryEvent = IngestRequested | AgentRequested | SourceAcquired
type PublicationEvent = DeliveryEvent


@dataclass(frozen=True)
class DeliveryPolicy:
    lease_seconds: int = 60
    heartbeat_seconds: int = 15
    concurrency: int = 2
    max_deliver: int = 20
    max_attempts: int = 5

    def __post_init__(self) -> None:
        if not (
            1 <= self.concurrency <= 2
            and 1 <= self.max_deliver <= 100
            and 1 <= self.max_attempts <= 5
            and 1 <= self.heartbeat_seconds < self.lease_seconds <= 60
        ):
            raise ValueError("Invalid bounded delivery policy")


def retry_delay(attempt: int) -> float:
    """Exponential bounded jitter; never exponentiate an unbounded attempt count."""
    return random.uniform(1.0, min(30.0, 2.0 ** min(max(0, attempt), 5)))


@dataclass(frozen=True)
class Lease:
    event: DeliveryEvent
    consumer: str
    owner: UUID
    token: int
    deadline: datetime
    attempt: int


@dataclass(frozen=True)
class Complete:
    result: RunResult | None = None


@dataclass(frozen=True)
class Deferred:
    delay_seconds: float = 30


@dataclass(frozen=True)
class Staged:
    """Handler committed a fenced checkpoint, continuation, and stage completion."""


@dataclass(frozen=True)
class PermanentFailure:
    code: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", self.code) is None:
            raise ValueError("Invalid safe failure code")


@dataclass(frozen=True)
class TransientFailure(PermanentFailure):
    pass


type Outcome = Complete | Deferred | Staged | PermanentFailure | TransientFailure


class Handler(Protocol):
    configured: bool

    async def handle(self, lease: Lease) -> Outcome:
        """Perform bounded external IO; checkpoint through a fenced repository."""


class UnconfiguredHandler:
    configured = False

    async def handle(self, lease: Lease) -> Outcome:
        return Deferred()


class LeaseLost(Exception):
    """The attempt cannot perform any further durable writes."""


@dataclass(frozen=True)
class OutboxClaim:
    event: PublicationEvent
    owner: UUID
    token: int
    attempt: int


def parse_event(data: bytes | str) -> DeliveryEvent:
    """Validate the canonical contract before authorization or processing."""
    try:
        return IngestRequested.model_validate_json(data)
    except ValueError:
        try:
            return AgentRequested.model_validate_json(data)
        except ValueError:
            return SourceAcquired.model_validate_json(data)


def parse_publication(data: bytes | str) -> PublicationEvent:
    """Validate events for the publisher and all durable consumers."""
    return parse_event(data)


SUBJECTS = {
    "indexer": "repo.ingest.requested",
    "agent": "agent.run.requested",
    "source": "repo.source.acquired",
}
PUBLICATION_SUBJECTS = tuple(SUBJECTS.values())
