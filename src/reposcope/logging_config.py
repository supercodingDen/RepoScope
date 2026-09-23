"""Secret-safe structured logging for runtime entry points."""

from __future__ import annotations

import json
import logging
from typing import Final

SAFE_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "code",
    "configuration_error",
    "event_id",
    "job_id",
    "request_id",
    "role",
    "run_id",
)


class JsonLogFormatter(logging.Formatter):
    """Serialize only explicitly safe fields and never exception text or tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one log record as a compact structured event."""
        payload: dict[str, str] = {"event": str(record.msg), "level": record.levelname}
        for field in SAFE_CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, str):
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
    for external_logger in ("nats", "psycopg", "redis"):
        logging.getLogger(external_logger).setLevel(logging.CRITICAL + 1)
