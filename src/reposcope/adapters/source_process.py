"""Bounded argument-array subprocesses with lifetime ownership of descendants."""

from __future__ import annotations

import ctypes
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import BinaryIO

from reposcope.domain.source import SourceLimits, SourceRejected


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IOLimit(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IOLimit),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _WindowsJob:
    """Assign a suspended process before any imported executable can create children."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise SourceRejected("SOURCE_PROCESS_ISOLATION")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = _ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x8
        limits.BasicLimitInformation.ActiveProcessLimit = 16
        if not self.handle or not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise SourceRejected("SOURCE_PROCESS_ISOLATION")

    def assign_and_resume(self, pid: int) -> None:
        if sys.platform != "win32":
            raise SourceRejected("SOURCE_PROCESS_ISOLATION")
        process = self.kernel.OpenProcess(0x1F0FFF, False, pid)
        try:
            if not process or not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise SourceRejected("SOURCE_PROCESS_ISOLATION")
            native = ctypes.WinDLL("ntdll")
            native.NtResumeProcess.argtypes = [wintypes.HANDLE]
            native.NtResumeProcess.restype = ctypes.c_long
            if native.NtResumeProcess(process) != 0:
                raise SourceRejected("SOURCE_PROCESS_ISOLATION")
        finally:
            if process:
                self.kernel.CloseHandle(process)

    def close(self) -> None:
        if sys.platform != "win32":
            return
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def bounded_disk_usage(root: Path, limits: SourceLimits) -> int:
    """Inspect owned storage only; never follow a link or reparse point."""
    total = 0
    count = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > limits.entry_count:
                    raise SourceRejected("SOURCE_ENTRY_LIMIT")
                # Windows enumeration metadata can retain the size from file creation
                # while a writer keeps its handle open. Fresh stat opens the handle.
                try:
                    info = Path(entry.path).stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise SourceRejected("SOURCE_LINK_REJECTED")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if total > limits.disk_bytes:
                        raise SourceRejected("SOURCE_DISK_LIMIT")
                else:
                    raise SourceRejected("SOURCE_SPECIAL_FILE")
    return total


class ProcessRunner:
    """Output and disk are monitored; physical disk may briefly overshoot the limit."""

    def __init__(self, root: Path, limits: SourceLimits, stop: threading.Event) -> None:
        self.root = root
        self.limits = limits
        self.stop = stop
        self.deadline = time.monotonic() + limits.deadline_seconds

    def check_time(self) -> None:
        if self.stop.is_set():
            raise SourceRejected("SOURCE_CANCELLED")
        if time.monotonic() >= self.deadline:
            raise SourceRejected("SOURCE_DEADLINE")

    def check(self) -> None:
        self.check_time()
        bounded_disk_usage(self.root, self.limits)
        self.check_time()

    def run(self, arguments: list[str], environment: dict[str, str], data: bytes = b"") -> bytes:
        self.check()
        job = _WindowsJob() if os.name == "nt" else None
        output = bytearray()
        diagnostics = bytearray()
        overflow = threading.Event()
        threads: list[threading.Thread] = []
        process: subprocess.Popen[bytes] | None = None

        def drain(stream: BinaryIO, capture: bool) -> None:
            size = 0
            try:
                while chunk := stream.read(8192):
                    size += len(chunk)
                    if size > self.limits.output_bytes:
                        overflow.set()
                    elif capture:
                        output.extend(chunk)
                    elif len(diagnostics) < 4096:
                        diagnostics.extend(chunk[: 4096 - len(diagnostics)])
            finally:
                stream.close()

        try:
            with (self.root / "command-input").open("w+b") as input_file:
                if len(data) > self.limits.output_bytes:
                    raise SourceRejected("SOURCE_OUTPUT_LIMIT")
                input_file.write(data)
                input_file.seek(0)
                process = subprocess.Popen(
                    arguments,
                    cwd=self.root,
                    env=environment,
                    stdin=input_file,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    start_new_session=os.name != "nt",
                    creationflags=(0x4 | 0x08000000) if os.name == "nt" else 0,
                )
                if job is not None:
                    job.assign_and_resume(process.pid)
                assert process.stdout is not None and process.stderr is not None
                for stream, capture in ((process.stdout, True), (process.stderr, False)):
                    thread = threading.Thread(target=drain, args=(stream, capture), daemon=True)
                    thread.start()
                    threads.append(thread)
                while process.poll() is None:
                    self.check()
                    if overflow.is_set():
                        raise SourceRejected("SOURCE_OUTPUT_LIMIT")
                    self.stop.wait(self.limits.poll_seconds)
                # Children may outlive a successful parent and retain pipe handles.
                if sys.platform == "win32":
                    assert job is not None
                    job.close()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for thread in threads:
                    thread.join(2)
                    if thread.is_alive():
                        raise SourceRejected("SOURCE_PROCESS_ISOLATION")
                self.check()
                if overflow.is_set():
                    raise SourceRejected("SOURCE_OUTPUT_LIMIT")
                if process.returncode != 0:
                    for marker, code in (
                        (b"not a git repository", "SOURCE_GIT_REPOSITORY"),
                        (b"Unsupported SSL backend", "SOURCE_TLS_BACKEND"),
                        (b"unable to find remote helper", "SOURCE_GIT_HELPER"),
                        (b"SSL certificate", "SOURCE_TLS_FAILED"),
                        (b"unknown option", "SOURCE_GIT_OPTION"),
                        (b"bad config", "SOURCE_GIT_CONFIG"),
                        (b"Could not resolve", "SOURCE_DNS_FAILED"),
                        (b"Failed to connect", "SOURCE_CONNECT_FAILED"),
                        (b"could not read Username", "SOURCE_NOT_PUBLIC"),
                        (b"curloptResolve", "SOURCE_DNS_PIN_FAILED"),
                        (b"too long", "SOURCE_PATH_TOO_LONG"),
                    ):
                        if marker.lower() in diagnostics.lower():
                            raise SourceRejected(code)
                    raise SourceRejected("SOURCE_GIT_FAILED")
                return bytes(output)
        finally:
            if job is not None:
                job.close()
            if process is not None:
                if sys.platform != "win32":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            for thread in threads:
                thread.join(2)
            (self.root / "command-input").unlink(missing_ok=True)
