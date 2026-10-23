"""Security policy checks used before a public source push."""

from __future__ import annotations

from scripts.publication_guard import forbidden_paths, populated_template_keys


def test_forbidden_paths_cover_host_secrets_and_nested_dotenv() -> None:
    assert forbidden_paths(
        [
            ".env.example",
            "deploy/.env.production",
            "deploy/secrets/openai_api_key",
            "backup.env",
            "server.pem",
            "docs/manual-configuration.md",
        ]
    ) == (
        "deploy/.env.production",
        "deploy/secrets/openai_api_key",
        "backup.env",
        "server.pem",
    )


def test_template_rejects_populated_credentials_without_echoing_values() -> None:
    assert populated_template_keys(
        "OPENAI_API_KEY=sample-value\nREPOSCOPE_API_TOKEN=\n# POSTGRES_PASSWORD=hidden\n"
    ) == ("OPENAI_API_KEY",)


def test_template_rejects_alternate_secret_assignment_forms() -> None:
    assert populated_template_keys(
        "OPENAI_API_KEY =sample-value\n"
        "export REPOSCOPE_API_TOKEN=sample-value\n"
        "GITHUB_TOKEN=sample-value\n"
        "AWS_ACCESS_KEY_ID=sample-value\n"
        "MAX_INPUT_TOKENS_PER_CALL=24000\n"
        "PROVIDER_MODE=mock\n"
    ) == (
        "OPENAI_API_KEY",
        "REPOSCOPE_API_TOKEN",
        "GITHUB_TOKEN",
        "AWS_ACCESS_KEY_ID",
    )
