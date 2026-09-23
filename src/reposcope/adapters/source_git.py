"""GitHub-only blobless object acquisition without checkout or imported execution."""

from __future__ import annotations

import os
import re
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from reposcope.adapters.source_process import ProcessRunner
from reposcope.adapters.source_storage import SnapshotBuilder, SourceStore
from reposcope.adapters.source_transport import BoundedGitProxy
from reposcope.domain.source import (
    SourceLimits,
    SourceRejected,
    canonical_repository,
    public_address,
)
from reposcope.domain.source_snapshot import SourceSnapshot

_SHA = re.compile(r"[a-f0-9]{40}")


def safe_reference(value: str) -> str:
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", value) is None
        or any(marker in value for marker in ("..", "//"))
        or value.endswith(("/", ".", ".lock"))
        or any(part.startswith(".") for part in value.split("/"))
    ):
        raise SourceRejected("INVALID_SOURCE_REF")
    return value


def choose_revision(reference: str, metadata: bytes) -> str:
    safe_reference(reference)
    candidates: dict[str, str] = {}
    try:
        for line in metadata.decode("ascii").splitlines():
            sha, name = line.split("\t", 1)
            if _SHA.fullmatch(sha) is None or name in candidates:
                raise SourceRejected("SOURCE_REF_INVALID")
            candidates[name] = sha
    except (UnicodeError, ValueError):
        raise SourceRejected("SOURCE_REF_INVALID") from None
    names = (
        [reference]
        if reference == "HEAD" or reference.startswith("refs/")
        else [
            "refs/heads/" + reference,
            "refs/tags/" + reference,
        ]
    )
    matches = [name for name in names if name in candidates]
    if len(matches) > 1:
        raise SourceRejected("SOURCE_REF_AMBIGUOUS")
    if len(matches) != 1:
        raise SourceRejected("SOURCE_REF_NOT_FOUND")
    selected = matches[0]
    return candidates.get(selected + "^{}", candidates[selected])


def isolated_environment(root: Path, binary: Path) -> dict[str, str]:
    home = root / "home"
    home.mkdir(exist_ok=True)
    environment = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
        "LANG": "C",
        "TMPDIR": str(root),
        "TMP": str(root),
        "TEMP": str(root),
        "PATH": str(binary.parent),
    }
    if sys.platform == "win32":
        system = os.environ.get("SystemRoot", r"C:\Windows")
        environment.update({"SystemRoot": system, "WINDIR": system})
        environment["PATH"] += os.pathsep + str(Path(system) / "System32")
    return environment


class GitSource:
    def __init__(self, binary: Path, store: SourceStore) -> None:
        if not binary.is_absolute() or not binary.is_file():
            raise SourceRejected("SOURCE_GIT_CONFIG")
        self.binary = binary
        self.store = store

    def cleanup_obsolete(self, job_id: UUID, tokens: tuple[int, ...]) -> None:
        for token in tokens:
            self.store.cleanup(self.store.root / "attempts" / f"{job_id}-{token}")
            self.store.cleanup_snapshot_attempt(job_id, token)

    @contextmanager
    def session(
        self, url: str, job_id: UUID, token: int, limits: SourceLimits, stop: threading.Event
    ) -> Iterator[GitSession]:
        canonical_repository(url)
        attempt = self.store.attempt(job_id, token)
        try:
            yield GitSession(self, attempt, url, job_id, limits, stop)
        finally:
            self.store.cleanup(attempt)


class GitSession:
    def __init__(
        self,
        source: GitSource,
        attempt: Path,
        url: str,
        job_id: UUID,
        limits: SourceLimits,
        stop: threading.Event,
    ) -> None:
        self.source = source
        self.attempt = attempt
        self.url = url
        self.job_id = job_id
        self.limits = limits
        self.runner = ProcessRunner(attempt, limits, stop)
        self.environment = isolated_environment(attempt, source.binary)
        self.git_dir = attempt / "objects.git"
        self.empty = attempt / "empty"
        self.empty.mkdir()
        self.git(
            ["init", "--bare", "--template=" + str(self.empty), str(self.git_dir)], repository=False
        )
        self.allowed_blobs: set[str] = set()
        self.transferred_bytes = 0

    def git(
        self,
        arguments: list[str],
        *,
        network: bool = False,
        repository: bool = True,
        data: bytes = b"",
    ) -> bytes:
        configuration = [
            "credential.helper=",
            "credential.interactive=false",
            "http.proxy=",
            "http.followRedirects=false",
            "http.sslVerify=true",
            "protocol.allow=never",
            "protocol.https.allow=always",
            "protocol.file.allow=never",
            "protocol.version=2",
            "core.hooksPath=" + str(self.empty),
            "core.attributesFile=" + os.devnull,
            "core.askPass=",
            "core.longpaths=true",
            "submodule.recurse=false",
            "fetch.recurseSubmodules=false",
            "fetch.fsckObjects=true",
            "transfer.fsckObjects=true",
            "fetch.writeCommitGraph=false",
            "gc.auto=0",
            "maintenance.auto=false",
            "http.extraHeader=",
            "safe.bareRepository=explicit",
            "remote.origin.promisor=false",
        ]
        approved: list[str] = []
        if network:
            # DNS itself runs inside an owned, bounded process so cancellation cannot abandon it.
            dns = self.runner.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import socket; print('\\n'.join(sorted({x[4][0] for x in "
                    "socket.getaddrinfo('github.com',443,type=socket.SOCK_STREAM)})))",
                ],
                self.environment,
            )
            try:
                addresses = dns.decode("ascii").splitlines()
                if not 1 <= len(addresses) <= 256:
                    raise SourceRejected("UNSAFE_SOURCE_ADDRESS")
                approved = [public_address(address) for address in addresses]
            except UnicodeError:
                raise SourceRejected("UNSAFE_SOURCE_ADDRESS") from None
            address = approved[0]
            if ":" in address:
                address = "[" + address + "]"
            configuration.append("http.curloptResolve=github.com:443:" + address)
            configuration.extend(["http.lowSpeedLimit=1", "http.lowSpeedTime=15"])
        command = [str(self.source.binary)]
        for setting in configuration:
            command.extend(["-c", setting])
        if repository:
            command.extend(["--git-dir=" + str(self.git_dir)])
        # Git for Windows normalizes Win32 paths itself with core.longpaths.
        command = [part.replace("\\\\?\\", "") for part in command + arguments]
        environment = {
            name: value.replace("\\\\?\\", "") for name, value in self.environment.items()
        }
        if not network:
            return self.runner.run(command, environment, data)
        remaining = self.limits.download_bytes - self.transferred_bytes
        if remaining <= 0:
            raise SourceRejected("SOURCE_DOWNLOAD_LIMIT")
        proxy = BoundedGitProxy(tuple(approved), remaining, self.runner.stop, self.runner.deadline)
        try:
            with proxy:
                # Explicit owned CONNECT transport overrides the deliberately empty proxy default.
                configured = command[:1] + ["-c", "http.proxy=" + proxy.url] + command[1:]
                # The later empty proxy configuration would override it; replace that exact setting.
                configured = [
                    "http.proxy=" + proxy.url if arg == "http.proxy=" else arg for arg in configured
                ]
                try:
                    result = self.runner.run(configured, environment, data)
                except SourceRejected:
                    proxy.check()
                    raise
                proxy.check()
                return result
        finally:
            self.transferred_bytes += proxy.transferred_bytes

    def _fetch(self, sha: str, filter_spec: str) -> None:
        if _SHA.fullmatch(sha) is None:
            raise SourceRejected("SOURCE_REF_INVALID")
        self.git(
            [
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules",
                "--depth=1",
                "--refetch",
                "--filter=" + filter_spec,
                self.url,
                sha,
            ],
            network=True,
        )
        self._objects()

    def _objects(self) -> dict[str, int]:
        output = self.git(
            [
                "cat-file",
                "--batch-all-objects",
                "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            ]
        )
        sizes: dict[str, int] = {}
        count = 0
        for line in output.splitlines():
            count += 1
            if count > self.limits.entry_count:
                raise SourceRejected("SOURCE_ENTRY_LIMIT")
            try:
                oid, kind, size = line.decode("ascii").split(" ")
                number = int(size)
            except (UnicodeError, ValueError):
                raise SourceRejected("SOURCE_OBJECT_INVALID") from None
            if kind == "blob":
                if oid not in self.allowed_blobs:
                    raise SourceRejected("SOURCE_FILTER_VIOLATION")
                sizes[oid] = number
        return sizes

    def resolve(self, reference: str) -> str:
        safe_reference(reference)
        if _SHA.fullmatch(reference):
            sha = reference
        else:
            patterns = (
                [reference, reference + "^{}"]
                if reference == "HEAD" or reference.startswith("refs/")
                else [
                    "refs/heads/" + reference,
                    "refs/tags/" + reference,
                    "refs/tags/" + reference + "^{}",
                ]
            )
            metadata = self.git(["ls-remote", "--", self.url, *patterns], network=True)
            sha = choose_revision(reference, metadata)
        # Verify actual commit before pinning; tree:0 negotiates metadata only.
        self._fetch(sha, "tree:0")
        if self.git(["cat-file", "-t", sha]).strip() != b"commit":
            raise SourceRejected("SOURCE_NOT_COMMIT")
        return sha

    def acquire(self, commit: str) -> SourceSnapshot:
        self._fetch(commit, "blob:none")
        if self.git(["cat-file", "-t", commit]).strip() != b"commit":
            raise SourceRejected("SOURCE_NOT_COMMIT")
        tree = self.git(["ls-tree", "-r", "-z", "--full-tree", commit])
        builder = SnapshotBuilder(self.attempt, self.limits)
        eligible: list[tuple[str, str]] = []
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            try:
                header, raw_path = entry.split(b"\t", 1)
                mode, kind, raw_oid = header.decode("ascii").split(" ")
                path = raw_path.decode("utf-8")
                oid = raw_oid
            except (ValueError, UnicodeError):
                raise SourceRejected("SOURCE_TREE_INVALID") from None
            if _SHA.fullmatch(oid) is None:
                raise SourceRejected("SOURCE_TREE_INVALID")
            if not builder.path(path):
                continue
            if mode == "120000":
                builder.skip("symlink")
            elif mode == "160000":
                builder.skip("submodule")
            elif kind != "blob" or mode not in {"100644", "100755"}:
                raise SourceRejected("SOURCE_TREE_INVALID")
            else:
                eligible.append((path, oid))
        oids = sorted({oid for _, oid in eligible})
        self.allowed_blobs.update(oids)
        for offset in range(0, len(oids), 128):
            self.git(
                [
                    "fetch",
                    "--quiet",
                    "--no-tags",
                    "--no-write-fetch-head",
                    "--no-recurse-submodules",
                    "--filter=blob:none",
                    self.url,
                    *oids[offset : offset + 128],
                ],
                network=True,
            )
            self._objects()
        sizes = self._objects()
        for path, oid in eligible:
            self.runner.check()
            size = sizes.get(oid)
            if size is None:
                raise SourceRejected("SOURCE_OBJECT_MISSING")
            if size > self.limits.file_bytes:
                builder.skip("oversized")
                continue
            content = self.git(["cat-file", "blob", oid])
            if len(content) != size:
                raise SourceRejected("SOURCE_OBJECT_INVALID")
            builder.add(path, content)
        self.runner.check()
        return self.source.store.finalize(
            self.attempt, self.job_id, builder.manifest(self.url, commit), self.runner
        )
