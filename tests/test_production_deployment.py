"""Offline checks for protected production startup and network boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.launch_from_secrets import (
    SecretConfigurationError,
    build_environment,
    read_secret,
)

ROOT = Path(__file__).resolve().parents[1]


def _secret(root: Path, name: str, value: str) -> None:
    (root / name).write_text(value, encoding="utf-8")


def test_runtime_secrets_are_process_only_and_url_encoded(tmp_path: Path) -> None:
    _secret(tmp_path, "app_database_password", "a@/:% secret long enough")
    _secret(tmp_path, "api_token", "different-long-api-token")
    environment = build_environment("api", {"PROVIDER_MODE": "mock"}, tmp_path)
    assert environment["DATABASE_URL"].startswith(
        "postgresql://reposcope_app:a%40%2F%3A%25%20secret%20long%20enough@"
    )
    assert environment["REPOSCOPE_API_TOKEN"] == "different-long-api-token"
    assert "OPENAI_API_KEY" not in environment


def test_migration_uses_separate_owner_password(tmp_path: Path) -> None:
    _secret(tmp_path, "postgres_password", "owner-password-long-enough")
    _secret(tmp_path, "app_database_password", "application-password-long-enough")
    environment = build_environment("migrate", {}, tmp_path)
    assert "reposcope_migrator:owner-password-long-enough" in environment["MIGRATION_DATABASE_URL"]
    assert environment["APP_DATABASE_PASSWORD"] == "application-password-long-enough"
    assert "REPOSCOPE_API_TOKEN" not in environment


def test_worker_has_no_api_token_mount(tmp_path: Path) -> None:
    _secret(tmp_path, "app_database_password", "application-password-long-enough")
    environment = build_environment("indexer", {}, tmp_path)
    assert "REPOSCOPE_API_TOKEN" not in environment


def test_live_mode_fails_closed_without_opt_in_and_key(tmp_path: Path) -> None:
    _secret(tmp_path, "app_database_password", "application-password-long-enough")
    with pytest.raises(SecretConfigurationError, match="paid-call opt-in"):
        build_environment("agent", {"PROVIDER_MODE": "openai"}, tmp_path)
    with pytest.raises(SecretConfigurationError, match="openai_api_key"):
        build_environment(
            "agent", {"PROVIDER_MODE": "openai", "ALLOW_PAID_API_CALLS": "true"}, tmp_path
        )


def test_secret_errors_do_not_echo_secret(tmp_path: Path) -> None:
    _secret(tmp_path, "api_token", "short-secret")
    with pytest.raises(SecretConfigurationError) as result:
        read_secret("api_token", tmp_path)
    assert "short-secret" not in str(result.value)


def test_production_compose_only_publishes_proxy_ports() -> None:
    deployment = yaml.safe_load((ROOT / "compose.production.yaml").read_text(encoding="utf-8"))
    services = deployment["services"]
    assert set(services) == {
        "proxy",
        "postgres",
        "redis",
        "nats",
        "migrate",
        "api",
        "indexer",
        "agent",
    }
    assert [name for name, service in services.items() if "ports" in service] == ["proxy"]
    assert services["proxy"]["ports"] == ["80:80", "443:443"]
    for name in ("postgres", "redis", "nats", "migrate"):
        assert services[name]["networks"] == ["backend"]
    assert deployment["networks"]["backend"]["internal"] is True
    assert deployment["networks"]["ingress"]["internal"] is True
    assert services["api"]["pull_policy"] == "never"
    assert "build" not in services["api"]
    assert "OPENAI_API_KEY" not in services["api"]["environment"]
    assert services["indexer"]["secrets"] == ["app_database_password"]
    assert services["agent"]["secrets"] == ["app_database_password"]


def test_live_overlay_mounts_provider_key_only_on_application_roles() -> None:
    overlay = yaml.safe_load((ROOT / "compose.production.live.yaml").read_text(encoding="utf-8"))
    assert set(overlay["services"]) == {"api", "indexer", "agent"}
    assert overlay["services"]["api"]["secrets"] == [
        "app_database_password",
        "api_token",
        "openai_api_key",
    ]
    for role in ("indexer", "agent"):
        assert overlay["services"][role]["secrets"] == [
            "app_database_password",
            "openai_api_key",
        ]
