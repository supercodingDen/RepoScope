"""Start a production role with credentials read from mounted secret files."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote


class SecretConfigurationError(ValueError):
    """A required production secret is missing or malformed."""


def read_secret(name: str, root: Path = Path("/run/secrets")) -> str:
    """Read one Docker secret without echoing its content in errors."""
    try:
        value = (root / name).read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as error:
        raise SecretConfigurationError(f"Cannot read production secret {name}.") from error
    if len(value) < 16 or "\x00" in value or "\n" in value or "\r" in value:
        raise SecretConfigurationError(f"Production secret {name} is invalid.")
    return value


def build_environment(role: str, source: dict[str, str], root: Path) -> dict[str, str]:
    """Produce a process-only environment for one supported runtime role."""
    if role not in {"api", "indexer", "agent", "migrate"}:
        raise SecretConfigurationError("Unsupported production role.")
    values = dict(source)
    database_password = read_secret(
        "postgres_password" if role == "migrate" else "app_database_password", root
    )
    database_user = "reposcope_migrator" if role == "migrate" else "reposcope_app"
    database_url = (
        f"postgresql://{database_user}:{quote(database_password, safe='')}@postgres:5432/reposcope"
    )
    if role == "migrate":
        values["MIGRATION_DATABASE_URL"] = database_url
        values["APP_DATABASE_PASSWORD"] = read_secret("app_database_password", root)
    else:
        values["DATABASE_URL"] = database_url
        if role == "api":
            values["REPOSCOPE_API_TOKEN"] = read_secret("api_token", root)
        if values.get("PROVIDER_MODE", "mock") == "openai":
            if values.get("ALLOW_PAID_API_CALLS") != "true":
                raise SecretConfigurationError("Live provider requires paid-call opt-in.")
            values["OPENAI_API_KEY"] = read_secret("openai_api_key", root)
    return values


def main(arguments: list[str] | None = None) -> int:
    """Replace this process with the selected RepoScope role."""
    args = sys.argv[1:] if arguments is None else arguments
    if len(args) != 1:
        print("Expected exactly one production role.", file=sys.stderr)
        return 2
    role = args[0]
    try:
        environment = build_environment(role, dict(os.environ), Path("/run/secrets"))
    except SecretConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    module = "reposcope.infrastructure.db.migrate" if role == "migrate" else "reposcope"
    command = [sys.executable, "-m", module]
    if role != "migrate":
        command.append(role)
    os.execve(sys.executable, command, environment)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
