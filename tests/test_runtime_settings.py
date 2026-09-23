"""Observable settings behavior for the T02 runtime."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from reposcope.settings import RuntimeSettings, SettingsValidationError


def test_settings_accept_mock_runtime_urls() -> None:
    """A complete mock-only runtime configuration chooses the API pool budget."""
    settings = RuntimeSettings.from_values(
        {
            "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
            "REDIS_URL": "redis://redis:6379/0",
            "NATS_URL": "nats://nats:4222",
            "ROLE": "api",
            "PROVIDER_MODE": "mock",
        }
    )

    assert settings.role == "api"
    assert settings.database_pool_size == 10
    assert settings.provider_mode == "mock"
    assert isinstance(settings.database_url, SecretStr)


def test_settings_reject_missing_urls_without_echoing_values() -> None:
    """Removing a required setting must not reveal another configured URL."""
    with pytest.raises(SettingsValidationError) as raised:
        RuntimeSettings.from_values(
            {
                "DATABASE_URL": "postgresql://runtime:top-secret@postgres/reposcope",
                "REDIS_URL": "redis://redis:6379/0",
                "ROLE": "agent",
                "PROVIDER_MODE": "mock",
            }
        )

    message = str(raised.value)
    assert "NATS_URL" in message
    assert "top-secret" not in message
    assert "postgresql://" not in message


def test_settings_reject_live_provider_mode() -> None:
    """Changing provider mode away from mock must prevent startup."""
    with pytest.raises(SettingsValidationError):
        RuntimeSettings.from_values(
            {
                "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
                "REDIS_URL": "redis://redis:6379/0",
                "NATS_URL": "nats://nats:4222",
                "ROLE": "indexer",
                "PROVIDER_MODE": "live",
            }
        )


def test_settings_accept_explicit_budgeted_openai_mode() -> None:
    settings = RuntimeSettings.from_values(
        {
            "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
            "REDIS_URL": "redis://redis:6379/0",
            "NATS_URL": "nats://nats:4222",
            "ROLE": "indexer",
            "PROVIDER_MODE": "openai",
            "ALLOW_PAID_API_CALLS": "true",
            "OPENAI_API_KEY": "test-key-never-logged",
            "EMBEDDING_DAILY_BUDGET_USD": "1.00",
            "EMBEDDING_PRICE_PER_MILLION_USD": "0.02",
            "EMBEDDING_PRICE_VERIFIED_DATE": datetime.now(UTC).date().isoformat(),
        }
    )
    assert settings.provider_mode == "openai"
    assert settings.allow_paid_api_calls
    assert settings.embedding_daily_budget_usd is not None
    assert "test-key-never-logged" not in repr(settings)


@pytest.mark.parametrize(
    "override",
    [
        {"ALLOW_PAID_API_CALLS": "false"},
        {"OPENAI_API_KEY": ""},
        {"EMBEDDING_DAILY_BUDGET_USD": "0"},
        {"EMBEDDING_PRICE_PER_MILLION_USD": "nan"},
        {"EMBEDDING_PRICE_VERIFIED_DATE": "2020-01-01"},
    ],
)
def test_openai_requires_explicit_budget_configuration(override: dict[str, str]) -> None:
    values = {
        "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
        "REDIS_URL": "redis://redis:6379/0",
        "NATS_URL": "nats://nats:4222",
        "ROLE": "indexer",
        "PROVIDER_MODE": "openai",
        "ALLOW_PAID_API_CALLS": "true",
        "OPENAI_API_KEY": "test-key",
        "EMBEDDING_DAILY_BUDGET_USD": "1.00",
        "EMBEDDING_PRICE_PER_MILLION_USD": "0.02",
        "EMBEDDING_PRICE_VERIFIED_DATE": datetime.now(UTC).date().isoformat(),
        **override,
    }
    with pytest.raises(SettingsValidationError):
        RuntimeSettings.from_values(values)


@pytest.mark.parametrize(
    "override",
    [
        {"ALLOW_PAID_API_CALLS": "true"},
        {"DATABASE_URL": "https://database.example"},
        {"REDIS_URL": "https://cache.example"},
        {"NATS_URL": "https://broker.example"},
        {"PROBE_TIMEOUT_SECONDS": "nan"},
    ],
)
def test_settings_reject_unsafe_runtime_values(override: dict[str, str]) -> None:
    """Paid mode, malformed connection schemes, and nonfinite timeouts block startup."""
    values = {
        "DATABASE_URL": "postgresql://runtime:secret@postgres/reposcope",
        "REDIS_URL": "redis://redis:6379/0",
        "NATS_URL": "nats://nats:4222",
        "ROLE": "api",
        "PROVIDER_MODE": "mock",
        **override,
    }

    with pytest.raises(SettingsValidationError):
        RuntimeSettings.from_values(values)
