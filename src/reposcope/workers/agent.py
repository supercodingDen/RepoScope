"""Agent role entry point; T02 deliberately consumes no business work."""

from __future__ import annotations

from reposcope.__main__ import main


def run() -> int:
    """Start the idle agent management process."""
    return main(("agent",))
