"""Safe business failure categories."""

from contracts.models import ErrorCode


class WorkError(Exception):
    """A classified failure whose raw context is never sent to clients."""

    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code)
        self.code = code
