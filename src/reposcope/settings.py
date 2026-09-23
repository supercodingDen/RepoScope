"""Validated, environment-only runtime configuration."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import SecretStr

Role = Literal["api", "indexer", "agent"]


class SettingsValidationError(ValueError):
    """Raised when startup configuration is missing or unsafe."""


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Environment-only settings shared by API and worker roles."""

    database_url: SecretStr
    redis_url: SecretStr
    nats_url: SecretStr
    role: Role
    provider_mode: Literal["mock"]
    allow_paid_api_calls: Literal[False]
    public_host: str
    public_port: int
    management_host: str
    management_port: int
    startup_timeout_seconds: float
    probe_timeout_seconds: float
    shutdown_timeout_seconds: float
    api_token: SecretStr = SecretStr("")
    principal_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    source_root: str | None = None
    git_binary: str | None = None
    source_import_root: str | None = None

    @property
    def database_pool_size(self) -> int:
        """Return the role-specific PostgreSQL connection budget."""
        return {"api": 10, "indexer": 5, "agent": 5}[self.role]

    @classmethod
    def from_values(cls, values: Mapping[str, str]) -> Self:
        """Validate supplied environment-style values with secret-safe errors."""
        database_url = _required(values, "DATABASE_URL")
        redis_url = _required(values, "REDIS_URL")
        nats_url = _required(values, "NATS_URL")
        _validate_url(database_url, ("postgresql", "postgres"))
        _validate_url(redis_url, ("redis", "rediss"))
        _validate_url(nats_url, ("nats", "tls"))
        role = _role(values.get("ROLE", "api"))
        provider_mode = values.get("PROVIDER_MODE", "mock")
        if provider_mode != "mock":
            raise SettingsValidationError("Only mock provider mode is allowed during T02.")
        if _boolean(values.get("ALLOW_PAID_API_CALLS", "false")):
            raise SettingsValidationError("Paid API calls are disabled during T02.")
        return cls(
            database_url=SecretStr(database_url),
            redis_url=SecretStr(redis_url),
            nats_url=SecretStr(nats_url),
            role=role,
            provider_mode="mock",
            allow_paid_api_calls=False,
            public_host=values.get("PUBLIC_HOST", "127.0.0.1"),
            public_port=_port(values.get("PUBLIC_PORT", "8000")),
            management_host=values.get("MANAGEMENT_HOST", "127.0.0.1"),
            management_port=_port(values.get("MANAGEMENT_PORT", "9000")),
            startup_timeout_seconds=_timeout(values.get("STARTUP_TIMEOUT_SECONDS", "10")),
            probe_timeout_seconds=_timeout(values.get("PROBE_TIMEOUT_SECONDS", "2")),
            shutdown_timeout_seconds=_timeout(values.get("SHUTDOWN_TIMEOUT_SECONDS", "10")),
            api_token=SecretStr(values.get("REPOSCOPE_API_TOKEN", "")),
            source_root=_absolute_path(values.get("REPOSCOPE_SOURCE_ROOT")),
            git_binary=_absolute_path(values.get("REPOSCOPE_GIT_BINARY")),
            source_import_root=_absolute_path(values.get("SOURCE_IMPORT_ROOT")),
            principal_id=_principal(
                values.get("REPOSCOPE_PRINCIPAL_ID", "00000000-0000-0000-0000-000000000001")
            ),
        )

    @classmethod
    def from_environment(cls) -> Self:
        """Load process environment only; this method never reads a dotenv file."""
        return cls.from_values(os.environ)


def _required(values: Mapping[str, str], name: str) -> str:
    """Return a required environment value without placing it in an error message."""
    value = values.get(name, "").strip()
    if not value:
        raise SettingsValidationError(f"Missing required setting: {name}.")
    return value


def _principal(value: str) -> UUID:
    """Validate the server-owned principal without echoing configuration."""
    try:
        return UUID(value)
    except ValueError:
        raise SettingsValidationError("REPOSCOPE_PRINCIPAL_ID must be a UUID.") from None


def _validate_url(value: str, allowed_schemes: tuple[str, ...]) -> None:
    """Require a supported connection URL with a network location."""
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise SettingsValidationError("A connection URL has an unsupported format.") from None
    if (
        parsed.scheme not in allowed_schemes
        or hostname is None
        or port is not None
        and not 1 <= port <= 65535
    ):
        raise SettingsValidationError("A connection URL has an unsupported format.")


def _role(value: str) -> Role:
    """Validate a deployable role name."""
    if value == "api":
        return "api"
    if value == "indexer":
        return "indexer"
    if value == "agent":
        return "agent"
    raise SettingsValidationError("Role must be api, indexer, or agent.")


def _boolean(value: str) -> bool:
    """Parse the small boolean environment surface used by T02."""
    if value.lower() in {"true", "1"}:
        return True
    if value.lower() in {"false", "0"}:
        return False
    raise SettingsValidationError("Boolean setting must be true or false.")


def _port(value: str) -> int:
    """Parse one valid TCP port."""
    try:
        port = int(value)
    except ValueError as error:
        raise SettingsValidationError("Port setting must be an integer.") from error
    if not 1 <= port <= 65535:
        raise SettingsValidationError("Port setting must be between 1 and 65535.")
    return port


def _timeout(value: str) -> float:
    """Parse one finite, positive operation timeout."""
    try:
        timeout = float(value)
    except ValueError as error:
        raise SettingsValidationError("Timeout setting must be a number.") from error
    if not math.isfinite(timeout) or not 0.0 < timeout <= 60.0:
        raise SettingsValidationError(
            "Timeout setting must be finite and between 0 and 60 seconds."
        )
    return timeout


def _absolute_path(value: str | None) -> str | None:
    if not value:
        return None
    if not Path(value).is_absolute():
        raise SettingsValidationError("Source paths must be absolute operator configuration.")
    return value
