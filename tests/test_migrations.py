"""Unit tests for deterministic migration discovery and safe configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from reposcope.infrastructure.db.migrate import (
    ConfigurationError,
    MigrationIntegrityError,
    discover_migrations,
    load_migration_config,
    validate_migration_history,
)


def _environment(
    database_url: str = "postgresql://reposcope_migrator:secret@postgres:5432/reposcope",
    password: str = "a-secure-runtime-password-123456",
) -> Mapping[str, str]:
    return {
        "MIGRATION_DATABASE_URL": database_url,
        "APP_DATABASE_PASSWORD": password,
    }


def test_discover_migrations_is_sorted_and_checksums_file_bytes(tmp_path: Path) -> None:
    migration_directory = tmp_path / "migrations"
    migration_directory.mkdir()
    (migration_directory / "0002_second.sql").write_bytes(b"SELECT 2;\r\n")
    (migration_directory / "0001_first.sql").write_bytes(b"SELECT 1;\n")

    migrations = discover_migrations(migration_directory)

    assert [migration.version for migration in migrations] == ["0001_first", "0002_second"]
    assert (
        migrations[0].checksum == "b4e0497804e46e0a0b0b8c31975b062152d551bac49c3c2e80932567b4085dcd"
    )
    assert (
        migrations[1].checksum == "c2fb0d1c749ca4844e0da66c12a21108d2505f9b0bfe070ce0ed099365a43e63"
    )


def test_validate_migration_history_rejects_unknown_database_version(tmp_path: Path) -> None:
    migration_directory = tmp_path / "migrations"
    migration_directory.mkdir()
    (migration_directory / "0001_bootstrap.sql").write_text("SELECT 1;\n", encoding="utf-8")

    migrations = discover_migrations(migration_directory)

    with pytest.raises(MigrationIntegrityError):
        validate_migration_history(migrations, {"0000_removed": "checksum"})


def test_validate_migration_history_rejects_changed_migration_checksum(tmp_path: Path) -> None:
    migration_directory = tmp_path / "migrations"
    migration_directory.mkdir()
    (migration_directory / "0001_bootstrap.sql").write_text("SELECT 1;\n", encoding="utf-8")

    migrations = discover_migrations(migration_directory)

    with pytest.raises(MigrationIntegrityError):
        validate_migration_history(migrations, {"0001_bootstrap": "modified"})


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"MIGRATION_DATABASE_URL": "postgresql://reposcope_migrator@postgres/reposcope"},
        {
            "MIGRATION_DATABASE_URL": "postgresql://reposcope_migrator@postgres/reposcope",
            "APP_DATABASE_PASSWORD": "too-short",
        },
        {
            "MIGRATION_DATABASE_URL": "https://postgres/reposcope",
            "APP_DATABASE_PASSWORD": "a-secure-runtime-password-123456",
        },
    ],
)
def test_load_migration_config_rejects_invalid_environment_without_revealing_values(
    environment: Mapping[str, str],
) -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_migration_config(environment)

    message = str(raised.value)
    assert "postgresql://" not in message
    assert "a-secure-runtime-password" not in message


def test_load_migration_config_accepts_valid_environment() -> None:
    config = load_migration_config(_environment())

    assert config.database_url.startswith("postgresql://")
    assert config.application_password == "a-secure-runtime-password-123456"
