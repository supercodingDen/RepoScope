"""Regression checks for the smoke runner's controlled Compose environment."""

from __future__ import annotations

import string

import pytest

from scripts.smoke_test import smoke_environment


def test_smoke_environment_removes_inherited_compose_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSE_ENV_FILES", "untrusted.env")
    monkeypatch.setenv("COMPOSE_PROFILES", "test")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "ambient-project")
    monkeypatch.setenv("DOCKER_HOST", "tcp://docker-host:2375")

    environment = smoke_environment(18001)

    assert environment["COMPOSE_DISABLE_ENV_FILE"] == "1"
    assert environment["API_PORT"] == "18001"
    assert environment["DOCKER_HOST"] == "tcp://docker-host:2375"
    assert all(
        not key.startswith("COMPOSE_") or key == "COMPOSE_DISABLE_ENV_FILE" for key in environment
    )
    assert environment["POSTGRES_PASSWORD"] != environment["APP_DATABASE_PASSWORD"]
    for password_name in ("POSTGRES_PASSWORD", "APP_DATABASE_PASSWORD"):
        password = environment[password_name]
        assert len(password) >= 32
        assert set(password) <= set(string.hexdigits)
