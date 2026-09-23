"""Apply RepoScope PostgreSQL migrations with a dedicated migration owner."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from importlib.resources.abc import Traversable
from urllib.parse import urlsplit

from psycopg import AsyncConnection, sql

APPLICATION_ROLE = "reposcope_app"
MIGRATIONS_SCHEMA = "reposcope"
MIGRATIONS_TABLE = "schema_migrations"
MIGRATION_LOCK_KEY = 4_892_138_220_781_169_305
MIGRATION_FILE_PATTERN = re.compile(r"^[0-9]{4,}_[a-z0-9_]+\.sql$")
CONNECT_TIMEOUT_SECONDS = 10
MIGRATION_TIMEOUT_SECONDS = 60


class ConfigurationError(ValueError):
    """Raised when required migration configuration is invalid."""


class MigrationIntegrityError(RuntimeError):
    """Raised when the database ledger differs from packaged migrations."""


@dataclass(frozen=True, repr=False)
class MigrationConfig:
    """Migration credentials and the runtime password, never safe to log."""

    database_url: str
    application_password: str


@dataclass(frozen=True)
class Migration:
    """One immutable SQL migration discovered from package resources."""

    version: str
    checksum: str
    sql_text: str = field(repr=False)


@dataclass(frozen=True)
class MigrationResult:
    """The versions applied by one completed migration transaction."""

    applied_versions: tuple[str, ...]


def load_migration_config(environment: Mapping[str, str] | None = None) -> MigrationConfig:
    """Validate migration configuration without revealing secret values in errors."""
    values = os.environ if environment is None else environment
    database_url = values.get("MIGRATION_DATABASE_URL", "")
    application_password = values.get("APP_DATABASE_PASSWORD", "")
    if not _is_valid_postgresql_url(database_url):
        raise ConfigurationError("MIGRATION_DATABASE_URL must be a valid PostgreSQL URL.")
    if len(application_password) < 16 or "\x00" in application_password:
        raise ConfigurationError(
            "APP_DATABASE_PASSWORD must contain at least 16 non-null characters."
        )
    return MigrationConfig(database_url=database_url, application_password=application_password)


def _is_valid_postgresql_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"postgresql", "postgres"}
        and parsed.hostname is not None
        and parsed.username is not None
        and parsed.path not in {"", "/"}
    )


def discover_migrations(directory: Traversable) -> tuple[Migration, ...]:
    """Return valid migration SQL files in stable lexical version order."""
    migration_files = sorted(
        (entry for entry in directory.iterdir() if entry.is_file() and entry.name.endswith(".sql")),
        key=lambda entry: entry.name,
    )
    migrations: list[Migration] = []
    previous_version: str | None = None
    for entry in migration_files:
        if MIGRATION_FILE_PATTERN.fullmatch(entry.name) is None:
            raise MigrationIntegrityError(
                "Migration files must use a numeric versioned SQL filename."
            )
        version = entry.name.removesuffix(".sql")
        if previous_version == version:
            raise MigrationIntegrityError("Migration versions must be unique.")
        sql_bytes = entry.read_bytes()
        if not sql_bytes.strip():
            raise MigrationIntegrityError("Migration SQL files must not be empty.")
        try:
            sql_text = sql_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MigrationIntegrityError("Migration SQL files must be UTF-8.") from error
        migrations.append(
            Migration(
                version=version,
                checksum=hashlib.sha256(sql_bytes).hexdigest(),
                sql_text=sql_text,
            )
        )
        previous_version = version
    if not migrations:
        raise MigrationIntegrityError("At least one migration SQL file is required.")
    return tuple(migrations)


def validate_migration_history(
    migrations: Sequence[Migration], database_history: Mapping[str, str]
) -> None:
    """Reject unknown or changed migration history before applying DDL."""
    packaged_checksums = {migration.version: migration.checksum for migration in migrations}
    for version, checksum in database_history.items():
        packaged_checksum = packaged_checksums.get(version)
        if packaged_checksum is None or packaged_checksum != checksum:
            raise MigrationIntegrityError(
                "Database migration history does not match packaged migrations."
            )


def packaged_migrations() -> tuple[Migration, ...]:
    """Discover migrations from the installed RepoScope package."""
    return discover_migrations(files("reposcope.infrastructure.db.migrations"))


async def run_migrations(
    config: MigrationConfig, migrations: Sequence[Migration] | None = None
) -> MigrationResult:
    """Apply all missing migrations atomically under a transaction-scoped advisory lock."""
    return await asyncio.wait_for(
        _run_migrations(config, migrations), timeout=MIGRATION_TIMEOUT_SECONDS
    )


async def _run_migrations(
    config: MigrationConfig, migrations: Sequence[Migration] | None
) -> MigrationResult:
    """Run migrations with connection cleanup when completed or cancelled."""
    discovered_migrations = (
        await asyncio.to_thread(packaged_migrations) if migrations is None else tuple(migrations)
    )
    connection: AsyncConnection[tuple[str, ...]] | None = None
    try:
        connection = await AsyncConnection[tuple[str, ...]].connect(
            config.database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS
        )
        async with connection.transaction():
            await connection.execute("SET LOCAL statement_timeout = '30s'")
            await connection.execute("SET LOCAL lock_timeout = '5s'")
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_KEY,))
            await _ensure_application_role(connection, config.application_password)
            await _ensure_migration_ledger(connection)
            database_history = await _read_migration_history(connection)
            validate_migration_history(discovered_migrations, database_history)
            applied_versions = await _apply_missing_migrations(
                connection, discovered_migrations, database_history
            )
            await _configure_runtime_privileges(connection)
        return MigrationResult(applied_versions=applied_versions)
    finally:
        if connection is not None:
            await connection.close()


async def _ensure_application_role(
    connection: AsyncConnection[tuple[str, ...]], application_password: str
) -> None:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)::text",
        (APPLICATION_ROLE,),
    )
    row = await cursor.fetchone()
    role_exists = row is not None and row[0] == "true"
    if not role_exists:
        statement = sql.SQL(
            "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS"
        ).format(sql.Identifier(APPLICATION_ROLE), sql.Literal(application_password))
        await connection.execute(statement)
        return
    statement = sql.SQL(
        "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOINHERIT NOREPLICATION NOBYPASSRLS"
    ).format(sql.Identifier(APPLICATION_ROLE))
    await connection.execute(statement)


async def _ensure_migration_ledger(connection: AsyncConnection[tuple[str, ...]]) -> None:
    schema = sql.Identifier(MIGRATIONS_SCHEMA)
    migrator = sql.Identifier("reposcope_migrator")
    ledger = sql.Identifier(MIGRATIONS_SCHEMA, MIGRATIONS_TABLE)
    await connection.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(schema, migrator)
    )
    await connection.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} (version text PRIMARY KEY, checksum text NOT NULL)"
        ).format(ledger)
    )


async def _read_migration_history(
    connection: AsyncConnection[tuple[str, ...]],
) -> dict[str, str]:
    ledger = sql.Identifier(MIGRATIONS_SCHEMA, MIGRATIONS_TABLE)
    cursor = await connection.execute(sql.SQL("SELECT version, checksum FROM {}").format(ledger))
    rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def _apply_missing_migrations(
    connection: AsyncConnection[tuple[str, ...]],
    migrations: Sequence[Migration],
    database_history: Mapping[str, str],
) -> tuple[str, ...]:
    ledger = sql.Identifier(MIGRATIONS_SCHEMA, MIGRATIONS_TABLE)
    applied_versions: list[str] = []
    for migration in migrations:
        if migration.version in database_history:
            continue
        await connection.execute(migration.sql_text)
        await connection.execute(
            sql.SQL("INSERT INTO {} (version, checksum) VALUES (%s, %s)").format(ledger),
            (migration.version, migration.checksum),
        )
        applied_versions.append(migration.version)
    return tuple(applied_versions)


async def _configure_runtime_privileges(connection: AsyncConnection[tuple[str, ...]]) -> None:
    database_name = await _current_database_name(connection)
    database = sql.Identifier(database_name)
    schema = sql.Identifier(MIGRATIONS_SCHEMA)
    application_role = sql.Identifier(APPLICATION_ROLE)
    migrator_role = sql.Identifier("reposcope_migrator")
    ledger = sql.Identifier(MIGRATIONS_SCHEMA, MIGRATIONS_TABLE)

    await connection.execute(
        sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC").format(database)
    )
    await connection.execute(
        sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM {}").format(
            database, application_role
        )
    )
    await connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    await connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(schema))
    await connection.execute(
        sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(schema, application_role)
    )
    await connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, application_role)
    )
    await connection.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(
            schema, application_role
        )
    )
    await connection.execute(
        sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema, application_role)
    )
    await connection.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(migrator_role, schema, application_role)
    )
    await connection.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT USAGE ON SEQUENCES TO {}"
        ).format(migrator_role, schema, application_role)
    )
    await connection.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON TABLE {} FROM {}").format(ledger, application_role)
    )
    await connection.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(ledger, application_role)
    )


async def _current_database_name(connection: AsyncConnection[tuple[str, ...]]) -> str:
    cursor = await connection.execute("SELECT current_database()")
    row = await cursor.fetchone()
    if row is None:
        raise MigrationIntegrityError("Database name could not be determined.")
    return row[0]


async def main() -> int:
    """Run migrations and emit only a safe status line for process supervisors."""
    try:
        config = load_migration_config()
        result = await run_migrations(config)
    except (ConfigurationError, MigrationIntegrityError):
        print("Migration failed due to invalid configuration or migration history.")
        return 1
    except Exception:
        print("Migration failed without exposing connection or credential details.")
        return 1
    print(f"Migration completed; applied {len(result.applied_versions)} migration(s).")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
