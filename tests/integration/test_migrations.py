"""Opt-in PostgreSQL integration checks for the one-shot migration process."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping

import psycopg.errors
import pytest
from psycopg import AsyncConnection

from reposcope.infrastructure.db.migrate import (
    Migration,
    MigrationConfig,
    MigrationIntegrityError,
    packaged_migrations,
    run_migrations,
)

pytestmark = pytest.mark.integration


def _integration_configuration() -> tuple[MigrationConfig, str]:
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to use a real PostgreSQL instance.")
    migration_database_url = os.environ.get("MIGRATION_DATABASE_URL")
    runtime_database_url = os.environ.get("DATABASE_URL")
    application_password = os.environ.get("APP_DATABASE_PASSWORD")
    if (
        migration_database_url is None
        or runtime_database_url is None
        or application_password is None
    ):
        raise RuntimeError(
            "RUN_INTEGRATION_TESTS=1 requires PostgreSQL DSNs and the application password."
        )
    return (
        MigrationConfig(
            database_url=migration_database_url,
            application_password=application_password,
        ),
        runtime_database_url,
    )


def test_enabled_integration_checks_require_all_connection_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUN_INTEGRATION_TESTS", "1")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_DATABASE_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="requires"):
        _integration_configuration()


async def _migration_history(config: MigrationConfig) -> Mapping[str, str]:
    connection = await AsyncConnection[tuple[str, ...]].connect(
        config.database_url, autocommit=True
    )
    try:
        cursor = await connection.execute(
            "SELECT version, checksum FROM reposcope.schema_migrations"
        )
        return {row[0]: row[1] for row in await cursor.fetchall()}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_migrations_are_idempotent_atomic_and_restrict_runtime_role() -> None:
    config, runtime_database_url = _integration_configuration()

    first_run = await run_migrations(config)
    second_run = await run_migrations(config)

    assert set(first_run.applied_versions).issubset(
        {
            "0001_bootstrap",
            "0002_core",
            "0003_delivery",
            "0004_source",
            "0005_index",
            "0006_agent",
            "0007_run_events",
        }
    )
    assert second_run.applied_versions == ()

    runtime_connection = await AsyncConnection[tuple[str, ...]].connect(
        runtime_database_url, autocommit=True
    )
    try:
        ledger_cursor = await runtime_connection.execute(
            "SELECT version FROM reposcope.schema_migrations WHERE version = '0001_bootstrap'"
        )
        assert await ledger_cursor.fetchone() == ("0001_bootstrap",)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await runtime_connection.execute(
                "CREATE TABLE reposcope.runtime_ddl_denied (id integer)"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await runtime_connection.execute(
                "INSERT INTO reposcope.schema_migrations (version, checksum) "
                "VALUES ('runtime_write_denied', 'denied')"
            )
    finally:
        await runtime_connection.close()

    migrations = packaged_migrations()
    rollback_sql = "CREATE TABLE reposcope.rollback_probe (id integer); SELECT 1 / 0;"
    failing_migration = Migration(
        version="0002_rollback_probe",
        checksum=hashlib.sha256(rollback_sql.encode("utf-8")).hexdigest(),
        sql_text=rollback_sql,
    )
    with pytest.raises(psycopg.errors.DivisionByZero):
        await run_migrations(config, (*migrations, failing_migration))

    history_after_failure = await _migration_history(config)
    assert "0002_rollback_probe" not in history_after_failure

    migration_connection = await AsyncConnection[tuple[str, ...]].connect(
        config.database_url, autocommit=True
    )
    try:
        exists_cursor = await migration_connection.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_class "
            "JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace "
            "WHERE pg_namespace.nspname = 'reposcope' AND pg_class.relname = 'rollback_probe'"
            ")::text"
        )
        assert await exists_cursor.fetchone() == ("false",)
        bootstrap_checksum = history_after_failure["0001_bootstrap"]
        try:
            await migration_connection.execute(
                "UPDATE reposcope.schema_migrations SET checksum = %s "
                "WHERE version = '0001_bootstrap'",
                ("checksum_drift",),
            )
            with pytest.raises(MigrationIntegrityError):
                await run_migrations(config)
        finally:
            await migration_connection.execute(
                "UPDATE reposcope.schema_migrations SET checksum = %s "
                "WHERE version = '0001_bootstrap'",
                (bootstrap_checksum,),
            )
    finally:
        await migration_connection.close()
