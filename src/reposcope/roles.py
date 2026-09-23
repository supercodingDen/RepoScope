"""Process entry-point support for the API, indexer, and agent roles."""

from __future__ import annotations

import asyncio
import logging
import math
import signal
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

import uvicorn
from fastapi import FastAPI
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from reposcope.adapters.embedding import MockEmbeddingProvider, OpenAIEmbeddingProvider
from reposcope.adapters.embedding_budget import PostgresEmbeddingBudget
from reposcope.adapters.nats_delivery import JetStreamBroker
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.adapters.postgres_index import PostgresIndexRepository
from reposcope.adapters.postgres_retrieval import PostgresRetrievalRepository
from reposcope.adapters.postgres_source import PostgresSourceRepository
from reposcope.adapters.postgres_work import PostgresWorkRepository
from reposcope.adapters.source_git import GitSource
from reposcope.adapters.source_storage import SourceStore
from reposcope.application.delivery import DeliveryWorker, OutboxPublisher, run_reconciler
from reposcope.application.index import IndexHandler
from reposcope.application.retrieval import RetrievalService
from reposcope.application.source import SourceAcquisitionHandler
from reposcope.application.work import WorkService
from reposcope.domain.delivery import Handler, UnconfiguredHandler
from reposcope.ports.embedding import EmbeddingProvider
from reposcope.runtime import ManagedDependencyProbe, RuntimeResources
from reposcope.settings import RuntimeSettings
from reposcope.transport.http.app import create_health_application, create_public_application

LOGGER = logging.getLogger("reposcope.roles")


class _ManagedUvicornServer(uvicorn.Server):
    """A server whose shared role lifecycle, rather than Uvicorn, owns signals."""

    @contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        """Leave process signal handling to the role that owns all servers."""
        yield


async def run_role(settings: RuntimeSettings) -> None:
    """Run the requested role until Uvicorn receives its shutdown signal."""
    resources = await RuntimeResources.connect(settings)
    management = create_health_application(resources, include_metrics=True)
    stopping = asyncio.Event()
    _install_signal_handlers(stopping)
    try:
        async with asyncio.TaskGroup() as group:
            if isinstance(resources.probe, ManagedDependencyProbe):
                repository = PostgresDeliveryRepository(resources.probe.database_pool)
                broker = JetStreamBroker(resources.probe.nats_client)
                await broker.setup()
                if settings.role == "api":
                    group.create_task(OutboxPublisher(repository, broker).run(stopping))
                    group.create_task(run_reconciler(repository, stopping))
                else:
                    handler = delivery_handler(settings, repository)
                    if isinstance(handler, SourceAcquisitionHandler):
                        group.create_task(handler.run_cleanup(stopping))
                        assert settings.source_root is not None
                        provider = embedding_provider(settings, resources.probe.database_pool)
                        index_handler = IndexHandler(
                            PostgresIndexRepository(repository),
                            SourceStore(Path(settings.source_root)),
                            provider,
                        )
                        index_handler.slots = handler.slots
                        group.create_task(
                            DeliveryWorker(repository, broker, "source", index_handler).run(
                                stopping
                            )
                        )
                    group.create_task(
                        DeliveryWorker(
                            repository,
                            broker,
                            settings.role,
                            handler,
                        ).run(stopping)
                    )
            if settings.role == "api":
                service = (
                    WorkService(PostgresWorkRepository(resources.probe.database_pool))
                    if isinstance(resources.probe, ManagedDependencyProbe)
                    else None
                )
                retrieval = (
                    RetrievalService(
                        PostgresRetrievalRepository(resources.probe.database_pool),
                        embedding_provider(settings, resources.probe.database_pool),
                    )
                    if isinstance(resources.probe, ManagedDependencyProbe)
                    else None
                )
                public = create_public_application(resources, settings, service, retrieval)
                group.create_task(
                    _serve(
                        public,
                        settings.public_host,
                        settings.public_port,
                        stopping,
                        settings.shutdown_timeout_seconds,
                    )
                )
            group.create_task(
                _serve(
                    management,
                    settings.management_host,
                    settings.management_port,
                    stopping,
                    settings.shutdown_timeout_seconds,
                )
            )
    finally:
        try:
            await asyncio.wait_for(resources.close(), timeout=settings.shutdown_timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.error(
                "role_shutdown_failed",
                extra={"event": "role_shutdown_failed", "role": settings.role},
            )


def embedding_provider(
    settings: RuntimeSettings, pool: AsyncConnectionPool[AsyncConnection[tuple[str]]]
) -> EmbeddingProvider:
    """Select the same versioned embedding space for indexing and search."""
    if settings.provider_mode == "openai":
        assert settings.embedding_daily_budget_usd is not None
        assert settings.embedding_price_per_million_usd is not None
        assert settings.embedding_price_verified_date is not None
        return OpenAIEmbeddingProvider(
            settings.openai_api_key.get_secret_value(),
            PostgresEmbeddingBudget(
                pool,
                settings.embedding_daily_budget_usd,
                settings.embedding_price_per_million_usd,
                settings.embedding_price_verified_date,
            ),
        )
    return MockEmbeddingProvider()


def delivery_handler(settings: RuntimeSettings, repository: PostgresDeliveryRepository) -> Handler:
    """Composition hook for source acquisition (T05) and agent execution (T08)."""
    if settings.role == "indexer" and settings.source_root and settings.git_binary:
        return SourceAcquisitionHandler(
            PostgresSourceRepository(repository),
            GitSource(Path(settings.git_binary), SourceStore(Path(settings.source_root))),
        )
    return UnconfiguredHandler()


def _install_signal_handlers(stopping: asyncio.Event) -> None:
    """Make one role-level signal handler request graceful shutdown from every server."""
    loop = asyncio.get_running_loop()
    for received_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(received_signal, stopping.set)
        except NotImplementedError:
            signal.signal(received_signal, _signal_handler(stopping))


def _signal_handler(stopping: asyncio.Event) -> Callable[[int, FrameType | None], None]:
    """Create the synchronous fallback needed by Windows event loops."""

    def handle_signal(_: int, __: FrameType | None) -> None:
        stopping.set()

    return handle_signal


async def _serve(
    application: FastAPI,
    host: str,
    port: int,
    stopping: asyncio.Event,
    shutdown_timeout_seconds: float,
) -> None:
    """Serve one private or public ASGI application without a reload process."""
    config = uvicorn.Config(
        application,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=max(1, math.ceil(shutdown_timeout_seconds)),
    )
    server = _ManagedUvicornServer(config)
    server_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(stopping.wait())
    try:
        completed, _ = await asyncio.wait(
            {server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if stop_task in completed:
            server.should_exit = True
        elif not stopping.is_set():
            raise RuntimeError("A role server exited before a shutdown signal.")
        await server_task
    except asyncio.CancelledError:
        server.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(server_task), timeout=10.0)
        except TimeoutError:
            server_task.cancel()
        raise
    finally:
        server.should_exit = True
        stop_task.cancel()
