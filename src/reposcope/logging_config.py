"""Secret-safe structured logging for runtime entry points."""

from __future__ import annotations

import json
import logging
import re
from typing import Final
from uuid import UUID

SAFE_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "code",
    "configuration_error",
    "error_code",
    "event_id",
    "job_id",
    "request_id",
    "role",
    "run_id",
    "resource",
)

_SYMBOL = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")


class JsonLogFormatter(logging.Formatter):
    """Serialize only explicitly safe fields and never exception text or tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one log record as a compact structured event."""
        raw_event = record.msg
        event = (
            raw_event
            if record.name.startswith("reposcope.")
            and isinstance(raw_event, str)
            and _SYMBOL.fullmatch(raw_event)
            else "external_log"
        )
        payload: dict[str, str] = {"event": event, "level": record.levelname}
        for field in SAFE_CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if not isinstance(value, str):
                continue
            if field.endswith("_id"):
                try:
                    UUID(value)
                except ValueError:
                    continue
            elif field in {"code", "error_code"}:
                if _CODE.fullmatch(value) is None:
                    continue
            elif field == "role" and value not in {"api", "indexer", "agent"}:
                continue
            elif field == "resource" and value not in {"nats", "redis", "database"}:
                continue
            elif field == "configuration_error" and value not in {
                "DATABASE_URL",
                "REDIS_URL",
                "NATS_URL",
            }:
                continue
            if value:
                payload[field] = value
        return json.dumps(payload, sort_keys=True)


def configure_logging() -> None:
    """Install the runtime formatter and suppress third-party connection error text."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for external_logger in ("nats", "psycopg", "redis", "httpx", "httpcore", "openai"):
        logging.getLogger(external_logger).setLevel(logging.CRITICAL + 1)
