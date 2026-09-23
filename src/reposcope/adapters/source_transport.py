"""Git-only CONNECT transport with pinned public addresses and shared byte bounds."""

from __future__ import annotations

import select
import socket
import threading
import time
from types import TracebackType

from reposcope.domain.source import SourceRejected, public_address


class BoundedGitProxy:
    """Count TLS transport payload in both directions, including protocol overhead.

    At most one byte beyond the budget is received to detect overflow; no byte
    beyond the budget is forwarded. Kernel socket buffers are not wire quotas.
    The caller must debit transferred_bytes across successive network commands.
    """

    def __init__(
        self,
        approved_addresses: tuple[str, ...],
        limit: int,
        stop: threading.Event,
        deadline: float,
    ) -> None:
        if not approved_addresses or len(approved_addresses) > 256 or limit < 1:
            raise SourceRejected("SOURCE_TRANSPORT_CONFIG")
        self.addresses = tuple(public_address(address) for address in approved_addresses)
        self.limit = limit
        self.stop = stop
        self.deadline = deadline
        self._guard = threading.Lock()
        self._budget_guard = threading.Lock()
        self._closed = threading.Event()
        self._failure: str | None = None
        self._transferred = 0
        self._sockets: set[socket.socket] = set()
        self._threads: list[threading.Thread] = []
        self._active = threading.BoundedSemaphore(4)
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self.url = ""

    @property
    def transferred_bytes(self) -> int:
        with self._budget_guard:
            return self._transferred

    def check(self) -> None:
        with self._guard:
            failure = self._failure
        if failure is not None:
            raise SourceRejected(failure)
        if self.stop.is_set():
            raise SourceRejected("SOURCE_CANCELLED")
        if time.monotonic() >= self.deadline:
            raise SourceRejected("SOURCE_DEADLINE")

    def __enter__(self) -> BoundedGitProxy:
        self.check()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            listener.settimeout(0.05)
        except BaseException:
            listener.close()
            raise
        self._listener = listener
        self.url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        self._accept_thread = threading.Thread(target=self._accept, daemon=True)
        self._accept_thread.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _track(self, connection: socket.socket) -> None:
        with self._guard:
            if self._closed.is_set():
                connection.close()
                raise SourceRejected("SOURCE_CANCELLED")
            self._sockets.add(connection)

    def _untrack(self, connection: socket.socket) -> None:
        with self._guard:
            self._sockets.discard(connection)
        connection.close()

    def _halt(self) -> None:
        self._closed.set()
        with self._guard:
            connections = tuple(self._sockets)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def _fail(self, code: str) -> None:
        with self._guard:
            if self._failure is None:
                self._failure = code
        self._halt()

    def close(self) -> None:
        self._halt()
        if self._listener is not None:
            self._listener.close()
        if self._accept_thread is not None:
            self._accept_thread.join(2)
        for thread in self._threads:
            thread.join(2)
        if any(thread.is_alive() for thread in self._threads) or (
            self._accept_thread is not None and self._accept_thread.is_alive()
        ):
            raise SourceRejected("SOURCE_TRANSPORT_SHUTDOWN")

    def _accept(self) -> None:
        assert self._listener is not None
        try:
            while not self._closed.is_set():
                self.check()
                try:
                    client, _ = self._listener.accept()
                except TimeoutError:
                    continue
                if len(self._threads) >= 512 or not self._active.acquire(blocking=False):
                    client.close()
                    raise SourceRejected("SOURCE_CONNECTION_LIMIT")
                try:
                    self._track(client)
                except BaseException:
                    self._active.release()
                    raise
                thread = threading.Thread(target=self._serve, args=(client,), daemon=True)
                self._threads.append(thread)
                thread.start()
        except SourceRejected as error:
            self._fail(error.code)
        except OSError:
            if not self._closed.is_set():
                self._fail("SOURCE_NETWORK_FAILED")

    def _request(self, client: socket.socket) -> None:
        client.settimeout(0.1)
        request = bytearray()
        request_deadline = min(self.deadline, time.monotonic() + 3)
        while not request.endswith(b"\r\n\r\n"):
            self.check()
            if len(request) >= 4096 or time.monotonic() >= request_deadline:
                raise SourceRejected("SOURCE_PROXY_REQUEST")
            try:
                chunk = client.recv(1)
            except TimeoutError:
                continue
            if not chunk:
                raise SourceRejected("SOURCE_PROXY_REQUEST")
            request.extend(chunk)
        first = bytes(request).split(b"\r\n", 1)[0]
        if first not in {
            b"CONNECT github.com:443 HTTP/1.1",
            b"CONNECT github.com:443 HTTP/1.0",
        }:
            raise SourceRejected("SOURCE_PROXY_REQUEST")

    def _connect_upstream(self) -> socket.socket:
        for address in self.addresses:
            self.check()
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            connection = socket.socket(family, socket.SOCK_STREAM)
            self._track(connection)
            connection.settimeout(max(0.01, min(1.0, self.deadline - time.monotonic())))
            try:
                # Numeric addresses only: no second DNS lookup or proxy lookup.
                connection.connect((address, 443))
                return connection
            except OSError:
                self._untrack(connection)
        raise SourceRejected("SOURCE_NETWORK_FAILED")

    def _read(self, connection: socket.socket) -> bytes:
        with self._budget_guard:
            available = self.limit - self._transferred
            if available < 0:
                raise SourceRejected("SOURCE_DOWNLOAD_LIMIT")
            chunk = connection.recv(min(16384, available + 1))
            self._transferred += len(chunk)
            if self._transferred > self.limit:
                raise SourceRejected("SOURCE_DOWNLOAD_LIMIT")
            return chunk

    def _relay(self, client: socket.socket, upstream: socket.socket) -> None:
        client.setblocking(False)
        upstream.setblocking(False)
        peers = {client: upstream, upstream: client}
        pending: dict[socket.socket, bytearray] = {client: bytearray(), upstream: bytearray()}
        ended: set[socket.socket] = set()
        shutdown: set[socket.socket] = set()
        while not self._closed.is_set():
            self.check()
            for source in ended:
                target = peers[source]
                if not pending[target] and target not in shutdown:
                    target.shutdown(socket.SHUT_WR)
                    shutdown.add(target)
            if len(ended) == 2 and not any(pending.values()):
                return
            readable = [
                source
                for source, target in peers.items()
                if source not in ended and not pending[target]
            ]
            writable = [target for target, content in pending.items() if content]
            reads, writes, _ = select.select(readable, writable, [], 0.05)
            for target in writes:
                try:
                    count = target.send(pending[target])
                except BlockingIOError:
                    continue
                if count == 0:
                    raise SourceRejected("SOURCE_NETWORK_FAILED")
                del pending[target][:count]
            for source in reads:
                try:
                    content = self._read(source)
                except BlockingIOError:
                    continue
                if not content:
                    ended.add(source)
                else:
                    pending[peers[source]].extend(content)

    def _serve(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            self._request(client)
            upstream = self._connect_upstream()
            self._track(upstream)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._relay(client, upstream)
        except SourceRejected as error:
            self._fail(error.code)
        except (OSError, ValueError):
            if not self._closed.is_set():
                self._fail("SOURCE_NETWORK_FAILED")
        finally:
            self._untrack(client)
            if upstream is not None:
                self._untrack(upstream)
            self._active.release()
