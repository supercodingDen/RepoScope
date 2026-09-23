"""Completion-before-ACK processing and finite publication/reconciliation loops."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from uuid import uuid4

from reposcope.domain.delivery import (
    SUBJECTS,
    Deferred,
    Handler,
    Lease,
    LeaseLost,
    Outcome,
    PermanentFailure,
    Staged,
    TransientFailure,
    parse_event,
    retry_delay,
)
from reposcope.ports.delivery import DeliveryBroker, DeliveryMessage, DeliveryRepository

LOGGER = logging.getLogger("reposcope.delivery")


async def pause(stopping: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stopping.wait(), seconds)


class OutboxPublisher:
    def __init__(self, repository: DeliveryRepository, broker: DeliveryBroker) -> None:
        self.repository = repository
        self.broker = broker
        self.owner = uuid4()

    async def publish_one(self) -> bool:
        claim = await self.repository.claim_outbox(self.owner)
        if claim is None:
            return False
        try:
            await self.broker.publish(claim.event)
            await self.repository.mark_published(claim)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.repository.retry_publication(claim, retry_delay(claim.attempt))
            LOGGER.warning(
                "publication_retry",
                extra={"event_id": str(claim.event.event_id), "error_code": "BROKER_UNAVAILABLE"},
            )
        return True

    async def run(self, stopping: asyncio.Event) -> None:
        while not stopping.is_set():
            try:
                worked = await self.publish_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                worked = False
                LOGGER.warning(
                    "publisher_unavailable", extra={"error_code": "DEPENDENCY_UNAVAILABLE"}
                )
            if not worked:
                await pause(stopping, 1)


class DeliveryWorker:
    def __init__(
        self,
        repository: DeliveryRepository,
        broker: DeliveryBroker,
        consumer: str,
        handler: Handler,
    ) -> None:
        if consumer not in SUBJECTS:
            raise ValueError("Unknown delivery consumer")
        self.repository = repository
        self.broker = broker
        self.consumer = consumer
        self.handler = handler
        self.owner = uuid4()

    async def process(self, message: DeliveryMessage) -> None:
        try:
            if len(message.data) > 65536:
                raise ValueError("Oversized event")
            event = parse_event(message.data)
            if message.subject != self.broker.subject(event.event_type) or (
                event.event_type != SUBJECTS[self.consumer]
            ):
                raise ValueError("Event subject mismatch")
        except ValueError:
            await self.repository.quarantine(message.data, self.consumer, "INVALID_EVENT")
            await message.term()
            await self.broker.flush()
            return
        if not await self.repository.authorized(event):
            await self.repository.quarantine(message.data, self.consumer, "UNAUTHORIZED_EVENT")
            await message.term()
            await self.broker.flush()
            return
        if await self.repository.completed(self.consumer, event.event_id):
            await message.ack_sync()
            return
        if not self.handler.configured:
            await message.nak(delay=30)
            return
        lease = await self.repository.claim(event, self.consumer, self.owner)
        if lease is None:
            # Another attempt owns the lease or the persisted backoff is still active.
            await message.nak(delay=5)
            return
        try:
            outcome = await self._handle(lease, message)
            if isinstance(outcome, Staged):
                if not await self.repository.completed(self.consumer, event.event_id):
                    raise LeaseLost()
            elif isinstance(outcome, Deferred):
                await self.repository.release(
                    lease, min(30, max(1, outcome.delay_seconds)), refund_attempt=True
                )
                await message.nak(delay=min(30, max(1, outcome.delay_seconds)))
                return
            elif isinstance(outcome, TransientFailure):
                await self._retry(lease, message)
                return
            else:
                await self.repository.finalize(lease, outcome)
            await message.ack_sync()
        except asyncio.CancelledError:
            # Shutdown is never a business failure. Best-effort release; expiry is the fallback.
            with contextlib.suppress(Exception):
                await self.repository.release(lease, 1, refund_attempt=True)
            raise
        except LeaseLost:
            # No ACK: a new owner or reconciler controls recovery.
            LOGGER.warning(
                "lease_lost", extra={"event_id": str(event.event_id), "error_code": "LEASE_LOST"}
            )
        except Exception:
            LOGGER.warning(
                "delivery_retry",
                extra={"event_id": str(event.event_id), "error_code": "HANDLER_UNAVAILABLE"},
            )
            with contextlib.suppress(LeaseLost):
                await self._retry(lease, message)

    async def _retry(self, lease: Lease, message: DeliveryMessage) -> None:
        if lease.attempt >= self.repository.policy.max_attempts:
            await self.repository.finalize(lease, PermanentFailure("ATTEMPTS_EXHAUSTED"))
            await message.ack_sync()
            return
        delay = retry_delay(lease.attempt)
        await self.repository.release(lease, delay)
        await message.nak(delay=delay)

    async def _handle(self, lease: Lease, message: DeliveryMessage) -> Outcome:
        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self.repository.policy.heartbeat_seconds)
                await self.repository.renew(lease)
                await message.in_progress()

        work = asyncio.create_task(self.handler.handle(lease))
        progress = asyncio.create_task(heartbeat())
        try:
            remaining = max(0, (lease.deadline - datetime.now(UTC)).total_seconds())
            async with asyncio.timeout(remaining):
                done, _ = await asyncio.wait({work, progress}, return_when=asyncio.FIRST_COMPLETED)
                if progress in done:
                    await progress
                    raise LeaseLost()
                return await work
        finally:
            work.cancel()
            progress.cancel()
            await asyncio.gather(work, progress, return_exceptions=True)

    async def run(self, stopping: asyncio.Event) -> None:
        async def slot() -> None:
            while not stopping.is_set():
                try:
                    message = await self.broker.fetch_one(self.consumer)
                    if message is not None:
                        await self.process(message)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.warning(
                        "consumer_unavailable", extra={"error_code": "DEPENDENCY_UNAVAILABLE"}
                    )
                    await pause(stopping, 1)

        tasks = [asyncio.create_task(slot()) for _ in range(self.repository.policy.concurrency)]
        try:
            await stopping.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def run_reconciler(repository: DeliveryRepository, stopping: asyncio.Event) -> None:
    while not stopping.is_set():
        try:
            await repository.reconcile()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.warning("reconciler_unavailable", extra={"error_code": "DEPENDENCY_UNAVAILABLE"})
        await pause(stopping, 30)
