"""Owned, immutable source snapshots and quiescent operator-only local imports."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import sys
import threading
import time
from pathlib import Path
from uuid import UUID

from reposcope.adapters.source_process import ProcessRunner
from reposcope.domain.source import (
    SourceLimits,
    SourceRejected,
    classify_content,
    classify_path,
    safe_relative_path,
)
from reposcope.domain.source_snapshot import (
    SourceFile,
    SourceLicense,
    SourceManifest,
    SourceSnapshot,
)


def _ordinary(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.stat(follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise SourceRejected("SOURCE_LINK_REJECTED")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise SourceRejected("SOURCE_SPECIAL_FILE")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SourceRejected("SOURCE_LINK_REJECTED")
    return info


def _sync_directory(path: Path) -> None:
    if sys.platform != "win32":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


class SourceStore:
    """Root must be a private operator-owned directory, never an imported tree."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise SourceRejected("SOURCE_STORAGE_CONFIG")
        for ancestor in (root, *root.parents):
            if ancestor.exists():
                _ordinary(ancestor, directory=True)
        root.mkdir(parents=True, exist_ok=True)
        resolved = str(root.resolve(strict=True))
        self.root = (
            Path("\\\\?\\" + resolved)
            if os.name == "nt" and not resolved.startswith("\\\\")
            else Path(resolved)
        )
        for name in ("attempts", "snapshots"):
            directory = self.root / name
            directory.mkdir(exist_ok=True)
            _ordinary(directory, directory=True)

    def attempt(self, job_id: UUID, token: int) -> Path:
        if token < 1:
            raise SourceRejected("SOURCE_STORAGE_CONFIG")
        path = self.root / "attempts" / f"{job_id}-{token}"
        try:
            path.mkdir()
        except FileExistsError:
            raise SourceRejected("SOURCE_ATTEMPT_EXISTS") from None
        (path / "snapshot").mkdir()
        (path / "snapshot" / "blobs").mkdir()
        return path

    def _remove_owned_tree(self, path: Path) -> None:
        """Concurrent missing entries are success; persistent sharing failures remain retryable."""
        for retry in range(5):
            try:
                _ordinary(path, directory=True)
                for directory, children, files in os.walk(path, followlinks=False):
                    for name in children:
                        try:
                            _ordinary(Path(directory) / name, directory=True)
                        except FileNotFoundError:
                            continue
                    for name in files:
                        item = Path(directory) / name
                        try:
                            info = _ordinary(item)
                            if not info.st_mode & stat.S_IWRITE:
                                item.chmod(info.st_mode | stat.S_IWRITE)
                        except FileNotFoundError:
                            continue
                shutil.rmtree(path)
                return
            except FileNotFoundError:
                if not path.exists():
                    return
                if retry == 4:
                    raise
            except PermissionError:
                if not path.exists():
                    return
                if retry == 4:
                    raise
            time.sleep(0.02 * (retry + 1))

    def cleanup(self, attempt: Path) -> None:
        """Caller owns this exact attempt; never delete by age or broad root glob."""
        if (
            attempt.parent != self.root / "attempts"
            or re.fullmatch(r"[a-f0-9-]{36}-[1-9][0-9]*", attempt.name) is None
        ):
            raise SourceRejected("SOURCE_STORAGE_CONFIG")
        self._remove_owned_tree(attempt)

    def finalize(
        self,
        attempt: Path,
        job_id: UUID,
        manifest: SourceManifest,
        monitor: ProcessRunner | None = None,
    ) -> SourceSnapshot:
        if attempt.parent != self.root / "attempts" or not attempt.name.startswith(
            str(job_id) + "-"
        ):
            raise SourceRejected("SOURCE_STORAGE_CONFIG")
        snapshot_directory = attempt / "snapshot"
        key = f"snapshots/{attempt.name}/{manifest.digest}"
        result = SourceSnapshot(manifest, key)
        destination = self.root / key
        created = False
        try:
            _write(snapshot_directory / "manifest.json", manifest.serialize().encode("utf-8"))
            _sync_directory(snapshot_directory / "blobs")
            _sync_directory(snapshot_directory)
            # Include the last content write and manifest bytes while both remain in the attempt.
            if monitor is not None:
                monitor.check()
            destination.parent.mkdir(exist_ok=True)
            _ordinary(destination.parent, directory=True)
            if not destination.exists():
                snapshot_directory.rename(destination)
                created = True
                _sync_directory(destination.parent)
            self.validate(result, monitor)
            # Hashing/validation can consume the remaining deadline or observe cancellation.
            if monitor is not None:
                monitor.check()
            return result
        except BaseException:
            if created:
                self._remove_owned_tree(destination)
            raise

    def validate(self, snapshot: SourceSnapshot, monitor: ProcessRunner | None = None) -> None:
        safe_relative_path(snapshot.storage_key)
        limits = SourceLimits()
        if len(snapshot.manifest.files) > limits.file_count:
            raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT")
        total = 0
        previous = ""
        for file in snapshot.manifest.files:
            if monitor is not None:
                monitor.check_time()
            safe_relative_path(file.path)
            if (
                file.path <= previous
                or not 0 <= file.size <= limits.file_bytes
                or re.fullmatch(r"[a-f0-9]{64}", file.sha256) is None
            ):
                raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT")
            total += file.size
            previous = file.path
        if total != snapshot.manifest.eligible_bytes or total > limits.source_bytes:
            raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT")
        directory = self.root / snapshot.storage_key
        try:
            for path in (directory.parent, directory, directory / "blobs"):
                _ordinary(path, directory=True)
            manifest_path = directory / "manifest.json"
            info = _ordinary(manifest_path)
            expected = snapshot.manifest.serialize().encode("utf-8")
            if info.st_size != len(expected) or manifest_path.read_bytes() != expected:
                raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT")
            expected_names = {file.sha256 for file in snapshot.manifest.files}
            names = set()
            for path in (directory / "blobs").iterdir():
                if monitor is not None:
                    monitor.check_time()
                if path.name not in expected_names:
                    raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT")
                _ordinary(path)
                names.add(path.name)
            if names != expected_names:
                raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT")
            for file in snapshot.manifest.files:
                if monitor is not None:
                    monitor.check_time()
                path = directory / "blobs" / file.sha256
                info = _ordinary(path)
                if (
                    info.st_size != file.size
                    or hashlib.sha256(path.read_bytes()).hexdigest() != file.sha256
                ):
                    raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT")
        except OSError:
            raise SourceRejected("SOURCE_SNAPSHOT_CORRUPT") from None

    def cleanup_snapshot_attempt(self, job_id: UUID, token: int) -> None:
        """Only after the repository proves this token obsolete and unreferenced."""
        if token < 1:
            raise SourceRejected("SOURCE_STORAGE_CONFIG")
        path = self.root / "snapshots" / f"{job_id}-{token}"
        self._remove_owned_tree(path)


class SnapshotBuilder:
    def __init__(self, attempt: Path, limits: SourceLimits) -> None:
        self.attempt = attempt
        self.limits = limits
        self.files: list[SourceFile] = []
        self.skipped: dict[str, int] = {}
        self.seen: set[str] = set()
        self.spellings: dict[str, str] = {}
        self.scanned = 0
        self.total = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def path(self, path: str) -> bool:
        safe_relative_path(path)
        self.scanned += 1
        if self.scanned > self.limits.entry_count:
            raise SourceRejected("SOURCE_ENTRY_LIMIT")
        if path.casefold() in self.seen:
            raise SourceRejected("SOURCE_PATH_COLLISION")
        self.seen.add(path.casefold())
        parts = path.split("/")
        for count in range(1, len(parts) + 1):
            prefix = "/".join(parts[:count])
            folded = prefix.casefold()
            if folded in self.spellings and self.spellings[folded] != prefix:
                raise SourceRejected("SOURCE_PATH_COLLISION")
            self.spellings[folded] = prefix
        reason = classify_path(path)
        if reason is not None:
            self.skip(reason)
            return False
        return True

    def add(self, path: str, content: bytes) -> None:
        if len(content) > self.limits.file_bytes:
            self.skip("oversized")
            return
        reason = classify_content(content)
        if reason is not None:
            self.skip(reason)
            return
        if len(self.files) >= self.limits.file_count:
            raise SourceRejected("SOURCE_FILE_LIMIT")
        self.total += len(content)
        if self.total > self.limits.source_bytes:
            raise SourceRejected("SOURCE_BYTE_LIMIT")
        digest = hashlib.sha256(content).hexdigest()
        destination = self.attempt / "snapshot" / "blobs" / digest
        if not destination.exists():
            _write(destination, content)
        self.files.append(SourceFile(path, digest, len(content)))

    def manifest(self, source: str, commit: str | None) -> SourceManifest:
        files = tuple(sorted(self.files, key=lambda file: file.path))
        licenses = tuple(
            SourceLicense(file.path, file.sha256)
            for file in files
            if file.path.rsplit("/", 1)[-1].casefold().split(".")[0]
            in {"license", "licence", "copying"}
        )
        return SourceManifest(
            source,
            commit,
            files,
            dict(sorted(self.skipped.items())),
            self.scanned,
            self.total,
            licenses,
        )


class LocalSourceImporter:
    """Only imports quiescent operator staging; no hostile host race-safety claim."""

    def __init__(self, store: SourceStore, import_root: Path | None) -> None:
        self.store = store
        self.import_root = import_root

    def acquire(
        self, name: str, job_id: UUID, token: int, limits: SourceLimits, stop: threading.Event
    ) -> SourceSnapshot:
        if self.import_root is None or not self.import_root.is_absolute():
            raise SourceRejected("LOCAL_IMPORT_DISABLED")
        safe_relative_path(name)
        if "/" in name:
            raise SourceRejected("UNSAFE_SOURCE_PATH")
        root = self.import_root / name
        for path in (self.import_root, *self.import_root.parents, root):
            _ordinary(path, directory=True)
        attempt = self.store.attempt(job_id, token)
        runner = ProcessRunner(attempt, limits, stop)
        builder = SnapshotBuilder(attempt, limits)
        pending = [(root, "")]
        try:
            while pending:
                directory, prefix = pending.pop()
                runner.check()
                _ordinary(directory, directory=True)
                with os.scandir(directory) as entries:
                    for entry in entries:
                        runner.check()
                        relative = prefix + entry.name
                        # Excluded sensitive names are never opened, even for classification.
                        if entry.name.casefold() == ".git":
                            builder.scanned += 1
                            builder.skip("metadata")
                            continue
                        eligible = builder.path(relative)
                        path = Path(entry.path)
                        info = path.stat(follow_symlinks=False)
                        if (
                            stat.S_ISLNK(info.st_mode)
                            or getattr(info, "st_file_attributes", 0) & 0x400
                        ):
                            raise SourceRejected("SOURCE_LINK_REJECTED")
                        if not eligible:
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            pending.append((path, relative + "/"))
                            continue
                        before = _ordinary(path)
                        if before.st_size > limits.file_bytes:
                            builder.skip("oversized")
                            continue
                        with path.open("rb") as stream:
                            opened = os.fstat(stream.fileno())
                            content = stream.read(limits.file_bytes + 1)
                            after = os.fstat(stream.fileno())
                        final = _ordinary(path)
                        identities = {
                            (
                                item.st_dev,
                                item.st_ino,
                                item.st_size,
                                item.st_mtime_ns,
                                item.st_nlink,
                            )
                            for item in (before, opened, after, final)
                        }
                        if len(identities) != 1:
                            raise SourceRejected("SOURCE_LOCAL_MUTATION")
                        builder.add(relative, content)
            runner.check()
            return self.store.finalize(
                attempt, job_id, builder.manifest("local:" + name, None), runner
            )
        finally:
            self.store.cleanup(attempt)
