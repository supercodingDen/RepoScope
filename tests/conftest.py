"""Use psycopg-compatible async event loops on every supported platform."""

import asyncio
from collections.abc import Callable


def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    return {"selector": asyncio.SelectorEventLoop}
