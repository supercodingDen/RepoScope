"""Reject tracked credential paths and populated public configuration templates."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

SENSITIVE_NAMES = frozenset(
    {
        "api_token",
        "openai_api_key",
        "postgres_password",
        "app_database_password",
        "restic_password",
        "production.env",
        "backup.env",
    }
)
SECRET_TEMPLATE_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "REPOSCOPE_API_TOKEN",
        "POSTGRES_PASSWORD",
        "APP_DATABASE_PASSWORD",
        "DATABASE_URL",
        "REDIS_URL",
        "NATS_URL",
    }
)
SECRET_KEY_SUFFIXES = ("_PASSWORD", "_TOKEN", "_SECRET", "_CREDENTIAL", "_KEY", "_KEY_ID")


def forbidden_paths(paths: Iterable[str]) -> tuple[str, ...]:
    """Return tracked paths whose names are reserved for operator secrets."""
    rejected: list[str] = []
    for raw in paths:
        path = PurePosixPath(raw)
        name = path.name.lower()
        if raw == ".env.example":
            continue
        if (
            name == ".env"
            or name.startswith(".env.")
            or name in SENSITIVE_NAMES
            or name.endswith((".pem", ".key", ".p12", ".secret", ".token"))
            or "secrets" in (part.lower() for part in path.parts[:-1])
        ):
            rejected.append(raw)
    return tuple(rejected)


def populated_template_keys(template: str) -> tuple[str, ...]:
    """Name secret-bearing template entries that have nonempty values."""
    populated: list[str] = []
    for line in template.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.removeprefix("export ").strip().upper()
        if value.strip() and (name in SECRET_TEMPLATE_KEYS or name.endswith(SECRET_KEY_SUFFIXES)):
            populated.append(name)
    return tuple(populated)


def main() -> int:
    """Check Git's tracked path list and the intentionally blank public template."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        print("Publication guard requires a Git checkout.")
        return 1
    try:
        paths = result.stdout.decode("utf-8").rstrip("\x00").split("\x00")
        template = (root / ".env.example").read_text(encoding="utf-8")
    except (UnicodeError, OSError):
        print("Publication guard could not inspect reviewed files.")
        return 1
    rejected = forbidden_paths(paths)
    populated = populated_template_keys(template)
    if rejected or populated:
        print(
            f"Publication guard failed: {len(rejected)} secret paths, "
            f"{len(populated)} populated template keys."
        )
        return 1
    print("Publication guard passed: no tracked secret paths or populated template keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
