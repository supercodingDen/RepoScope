"""Controlled Git tunnel transport enforces destination and aggregate byte limits."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit

import pytest

from reposcope.adapters.source_transport import BoundedGitProxy
from reposcope.domain.source import SourceRejected


@contextmanager
def upstream_server(payload: bytes) -> Iterator[int]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    port = listener.getsockname()[1]

    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                connection.recv(1024)
                connection.sendall(payload)
        except OSError:
            pass

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield port
    finally:
        listener.close()
        thread.join(3)
        assert not thread.is_alive()


def client(proxy: BoundedGitProxy) -> socket.socket:
    port = urlsplit(proxy.url).port
    assert port is not None
    result = socket.create_connection(("127.0.0.1", port), timeout=2)
    return result


def test_exact_destination_and_payload_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    with upstream_server(b"x" * 5000) as port:

        def connect(proxy: BoundedGitProxy) -> socket.socket:
            return socket.create_connection(("127.0.0.1", port), timeout=2)

        monkeypatch.setattr(BoundedGitProxy, "_connect_upstream", connect)
        with BoundedGitProxy(("8.8.8.8",), 512, threading.Event(), time.monotonic() + 5) as proxy:
            with client(proxy) as stream:
                stream.sendall(b"CONNECT github.com:443 HTTP/1.1\r\nHost: github.com:443\r\n\r\n")
                assert b"200 Connection Established" in stream.recv(1024)
                stream.sendall(b"test")
                received = bytearray()
                while chunk := stream.recv(1024):
                    received.extend(chunk)
                assert len(received) <= 508
            with pytest.raises(SourceRejected, match="SOURCE_DOWNLOAD_LIMIT"):
                proxy.check()
            assert proxy.transferred_bytes <= 513


@pytest.mark.parametrize(
    "target", ["127.0.0.1:443", "github.com:80", "evil.example:443", "github.com.evil:443"]
)
def test_tunnel_rejects_other_destinations(target: str) -> None:
    with BoundedGitProxy(("8.8.8.8",), 1024, threading.Event(), time.monotonic() + 5) as proxy:
        with client(proxy) as stream:
            stream.sendall(f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
            assert stream.recv(1024) == b""
        with pytest.raises(SourceRejected, match="SOURCE_PROXY_REQUEST"):
            proxy.check()


def test_private_upstream_and_cancelled_context_rejected() -> None:
    with pytest.raises(SourceRejected):
        BoundedGitProxy(("127.0.0.1",), 1024, threading.Event(), time.monotonic() + 5)
    stop = threading.Event()
    stop.set()
    with pytest.raises(SourceRejected, match="SOURCE_CANCELLED"):
        with BoundedGitProxy(("8.8.8.8",), 1024, stop, time.monotonic() + 5):
            pass


def test_successful_tunnels_share_one_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    with BoundedGitProxy(("8.8.8.8",), 50, threading.Event(), time.monotonic() + 5) as proxy:
        for _ in range(2):
            with upstream_server(b"x" * 20) as port:

                def connect(proxy: BoundedGitProxy) -> socket.socket:
                    return socket.create_connection(("127.0.0.1", port), timeout=2)

                monkeypatch.setattr(BoundedGitProxy, "_connect_upstream", connect)
                with client(proxy) as stream:
                    stream.sendall(b"CONNECT github.com:443 HTTP/1.1\r\n\r\n")
                    assert b"200 Connection Established" in stream.recv(1024)
                    stream.sendall(b"test")
                    received = bytearray()
                    while chunk := stream.recv(1024):
                        received.extend(chunk)
                    assert received == b"x" * 20
        assert proxy.transferred_bytes == 48
        proxy.check()
        with upstream_server(b"x") as port:
            with client(proxy) as stream:
                stream.sendall(b"CONNECT github.com:443 HTTP/1.1\r\n\r\n")
                assert b"200 Connection Established" in stream.recv(1024)
                stream.sendall(b"test")
                try:
                    assert stream.recv(1024) == b""
                except ConnectionResetError:
                    pass
        with pytest.raises(SourceRejected, match="SOURCE_DOWNLOAD_LIMIT"):
            proxy.check()
        assert proxy.transferred_bytes == 51


def test_cancellation_closes_idle_client() -> None:
    stop = threading.Event()
    with BoundedGitProxy(("8.8.8.8",), 1024, stop, time.monotonic() + 5) as proxy:
        with client(proxy) as stream:
            stream.sendall(b"CONNECT ")
            stop.set()
            try:
                assert stream.recv(1024) == b""
            except ConnectionResetError:
                pass
        with pytest.raises(SourceRejected, match="SOURCE_CANCELLED"):
            proxy.check()


def test_connection_count_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[socket.socket] = []

    def connect(proxy: BoundedGitProxy) -> socket.socket:
        left, right = socket.socketpair()
        held.append(right)
        return left

    monkeypatch.setattr(BoundedGitProxy, "_connect_upstream", connect)
    clients: list[socket.socket] = []
    try:
        with BoundedGitProxy(("8.8.8.8",), 1024, threading.Event(), time.monotonic() + 5) as proxy:
            for _ in range(4):
                stream = client(proxy)
                clients.append(stream)
                stream.sendall(b"CONNECT github.com:443 HTTP/1.1\r\n\r\n")
                assert b"200 Connection Established" in stream.recv(1024)
            with client(proxy) as stream:
                assert stream.recv(1024) == b""
            with pytest.raises(SourceRejected, match="SOURCE_CONNECTION_LIMIT"):
                proxy.check()
    finally:
        for stream in (*clients, *held):
            stream.close()


@pytest.mark.parametrize("reverse", [False, True])
def test_tcp_half_close_preserves_delayed_response(reverse: bool) -> None:
    with BoundedGitProxy(("8.8.8.8",), 1024, threading.Event(), time.monotonic() + 5) as proxy:
        left, client_side = socket.socketpair()
        upstream_side, right = socket.socketpair()
        errors: list[BaseException] = []

        def relay() -> None:
            try:
                proxy._relay(client_side, upstream_side)
            except BaseException as error:
                errors.append(error)
            finally:
                client_side.close()
                upstream_side.close()

        worker = threading.Thread(target=relay)
        worker.start()
        sender, responder = (right, left) if reverse else (left, right)
        try:
            sender.settimeout(2)
            responder.settimeout(2)
            sender.sendall(b"request")
            sender.shutdown(socket.SHUT_WR)
            assert responder.recv(1024) == b"request"
            assert responder.recv(1024) == b""
            time.sleep(0.05)
            responder.sendall(b"delayed response")
            responder.shutdown(socket.SHUT_WR)
            assert sender.recv(1024) == b"delayed response"
            assert sender.recv(1024) == b""
        finally:
            left.close()
            right.close()
            worker.join(3)
        assert not worker.is_alive()
        assert not errors
