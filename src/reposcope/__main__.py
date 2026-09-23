"""Command-line entry point for RepoScope deployable roles."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import replace

from reposcope.logging_config import configure_logging
from reposcope.roles import run_role
from reposcope.settings import RuntimeSettings, SettingsValidationError

LOGGER = logging.getLogger("reposcope.command")


def main(arguments: Sequence[str] | None = None) -> int:
    """Start one selected role with environment-only configuration."""
    configure_logging()
    _configure_event_loop_policy()
    parser = argparse.ArgumentParser(prog="reposcope")
    parser.add_argument("role", choices=("api", "indexer", "agent"))
    parsed = parser.parse_args(arguments)
    try:
        settings = replace(RuntimeSettings.from_environment(), role=parsed.role)
    except SettingsValidationError as error:
        missing = re.fullmatch(
            r"Missing required setting: (DATABASE_URL|REDIS_URL|NATS_URL)\.", str(error)
        )
        LOGGER.error(
            "startup_configuration_invalid",
            extra={
                "code": "CONFIGURATION_INVALID",
                "configuration_error": missing.group(1) if missing else "UNSPECIFIED",
            },
        )
        return 1
    try:
        asyncio.run(run_role(settings))
    except KeyboardInterrupt:
        return 0
    except Exception:
        LOGGER.error("startup_failed", extra={"code": "STARTUP_FAILED", "role": settings.role})
        return 1
    return 0


def _configure_event_loop_policy() -> None:
    """Use the Windows selector loop required by the async NATS client."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    raise SystemExit(main())
