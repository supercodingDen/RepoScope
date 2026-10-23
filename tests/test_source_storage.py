"""Immutable snapshots and trusted local staging boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from reposcope.adapters.source_process import ProcessRunner
from reposcope.adapters.source_storage import LocalSourceImporter, SnapshotBuilder, SourceStore
from reposcope.domain.source import SourceLimits, SourceRejected
from reposcope.domain.source_snapshot import SourceSnapshot


def test_local_snapshot_is_sorted_and_immutable(tmp_path: Path) -> None:
    imports = tmp_path / "imports"
    source = imports / "sample"
    source.mkdir(parents=True)
    (source / "z.py").write_text("answer = 42\n")
    (source / "a.txt").write_text("hello\n")
    (source / ".env").write_text("NEVER_COPY_ME")
    (source / "LICENSE").write_text("Unrecognized terms")
    importer = LocalSourceImporter(SourceStore(tmp_path / "store"), imports)
    snapshot = importer.acquire("sample", uuid4(), 1, SourceLimits(), threading.Event())
    assert [file.path for file in snapshot.manifest.files] == ["LICENSE", "a.txt", "z.py"]
    assert snapshot.manifest.commit_sha is None
    assert snapshot.manifest.source == "local:sample"
    assert snapshot.manifest.skipped == {"secret": 1}
    assert snapshot.manifest.licenses[0].identifier == "unknown"
    (source / "z.py").write_text("changed")
    importer.store.validate(snapshot)
    again = importer.acquire("sample", uuid4(), 1, SourceLimits(), threading.Event())
    assert snapshot.digest != again.digest


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "x/y", ".", ".."])
def test_local_names_are_single_safe_components(tmp_path: Path, name: str) -> None:
    with pytest.raises(SourceRejected):
        LocalSourceImporter(SourceStore(tmp_path / "store"), tmp_path).acquire(
            name, uuid4(), 1, SourceLimits(), threading.Event()
        )


def test_local_hardlink_rejected(tmp_path: Path) -> None:
    imports = tmp_path / "imports"
    source = imports / "sample"
    source.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("do not copy")
    (source / "linked").hardlink_to(outside)
    with pytest.raises(SourceRejected, match="SOURCE_LINK_REJECTED"):
        LocalSourceImporter(SourceStore(tmp_path / "store"), imports).acquire(
            "sample", uuid4(), 1, SourceLimits(), threading.Event()
        )


def test_storage_corruption_cannot_be_reused(tmp_path: Path) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / "a.py").write_text("x = 1")
    store = SourceStore(tmp_path / "store")
    snapshot = LocalSourceImporter(store, source.parent).acquire(
        "sample", uuid4(), 1, SourceLimits(), threading.Event()
    )
    blob = store.root / snapshot.storage_key / "blobs" / snapshot.manifest.files[0].sha256
    blob.write_text("corrupt")
    with pytest.raises(SourceRejected, match="SOURCE_SNAPSHOT_CORRUPT"):
        store.validate(snapshot)


@pytest.mark.parametrize("limits", [SourceLimits(file_count=1), SourceLimits(source_bytes=3)])
def test_local_eligible_bounds(tmp_path: Path, limits: SourceLimits) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / "a").write_text("hello")
    (source / "b").write_text("world")
    with pytest.raises(SourceRejected, match="SOURCE_(FILE|BYTE)_LIMIT"):
        LocalSourceImporter(SourceStore(tmp_path / "store"), source.parent).acquire(
            "sample", uuid4(), 1, limits, threading.Event()
        )


def test_windows_junction_escape_rejected(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Native Windows reparse point gate")
    root = tmp_path / "imports"
    source = root / "sample"
    source.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "public.txt").write_text("outside fixture")
    junction = source / "junction"
    result = subprocess.run(
        [
            str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(junction),
            str(outside),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0
    with pytest.raises(SourceRejected, match="SOURCE_LINK_REJECTED"):
        LocalSourceImporter(SourceStore(tmp_path / "store"), root).acquire(
            "sample", uuid4(), 1, SourceLimits(), threading.Event()
        )
    assert (outside / "public.txt").read_text() == "outside fixture"


def test_reproducible_local_manifest_and_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / "a.txt").write_bytes(b"plain text\n")
    importer = LocalSourceImporter(SourceStore(tmp_path / "store"), source.parent)
    job_id = uuid4()
    first = importer.acquire("sample", job_id, 1, SourceLimits(), threading.Event())
    second = importer.acquire("sample", job_id, 1, SourceLimits(), threading.Event())
    assert first == second
    blob = importer.store.root / first.storage_key / "blobs" / first.manifest.files[0].sha256
    blob.write_bytes(b"corrupted")
    with pytest.raises(SourceRejected, match="SOURCE_SNAPSHOT_CORRUPT"):
        importer.acquire("sample", job_id, 1, SourceLimits(), threading.Event())


def test_casefold_directory_collision_rejected(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    attempt = store.attempt(uuid4(), 1)
    try:
        builder = SnapshotBuilder(attempt, SourceLimits())
        assert builder.path("Foo/a.py")
        with pytest.raises(SourceRejected, match="SOURCE_PATH_COLLISION"):
            builder.path("foo/b.py")
    finally:
        store.cleanup(attempt)


def test_entry_limit_also_bounds_exclusions(tmp_path: Path) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / ".env.one").write_text("synthetic excluded fixture")
    (source / ".env.two").write_text("synthetic excluded fixture")
    with pytest.raises(SourceRejected, match="SOURCE_ENTRY_LIMIT"):
        LocalSourceImporter(SourceStore(tmp_path / "store"), source.parent).acquire(
            "sample", uuid4(), 1, SourceLimits(entry_count=1), threading.Event()
        )


@pytest.mark.parametrize("budget", [1, 120])
def test_final_file_and_manifest_are_inside_disk_budget(tmp_path: Path, budget: int) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / "one.txt").write_bytes(b"x" * 100)
    importer = LocalSourceImporter(SourceStore(tmp_path / "store"), source.parent)
    with pytest.raises(SourceRejected, match="SOURCE_DISK_LIMIT"):
        importer.acquire("sample", uuid4(), 1, SourceLimits(disk_bytes=budget), threading.Event())
    assert not list((importer.store.root / "attempts").iterdir())
    assert not list((importer.store.root / "snapshots").glob("*/*"))


@pytest.mark.parametrize("existing", [False, True])
def test_final_hash_check_obeys_deadline_and_preserves_existing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / "one.txt").write_bytes(b"x" * 100)
    importer = LocalSourceImporter(SourceStore(tmp_path / "store"), source.parent)
    job = uuid4()
    old = (
        importer.acquire("sample", job, 1, SourceLimits(), threading.Event()) if existing else None
    )
    validate = importer.store.validate

    def slow_validate(snapshot: SourceSnapshot, monitor: ProcessRunner | None = None) -> None:
        validate(snapshot, monitor)
        time.sleep(0.04)

    monkeypatch.setattr(importer.store, "validate", slow_validate)
    with pytest.raises(SourceRejected, match="SOURCE_DEADLINE"):
        importer.acquire("sample", job, 1, SourceLimits(deadline_seconds=0.03), threading.Event())
    assert not list((importer.store.root / "attempts").iterdir())
    if old is not None:
        validate(old)
    else:
        assert not list((importer.store.root / "snapshots").glob("*/*"))


def test_concurrent_cleanup_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "store"
    first = SourceStore(root)
    second = SourceStore(root)
    attempt = first.attempt(uuid4(), 1)
    for number in range(100):
        (attempt / str(number)).write_bytes(b"owned fixture")
    barrier = threading.Barrier(2)

    def cleanup(store: SourceStore) -> None:
        barrier.wait()
        store.cleanup(attempt)

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(cleanup, store) for store in (first, second)]
        for future in futures:
            future.result(timeout=5)
    assert not attempt.exists()


def test_cleanup_rejects_persistent_hardlink(tmp_path: Path) -> None:
    store = SourceStore(tmp_path / "store")
    attempt = store.attempt(uuid4(), 1)
    outside = tmp_path / "outside"
    outside.write_bytes(b"retain")
    (attempt / "linked").hardlink_to(outside)

    with pytest.raises(SourceRejected, match="SOURCE_LINK_REJECTED"):
        store.cleanup(attempt)
    assert outside.read_bytes() == b"retain"
    assert (attempt / "linked").exists()


def test_validation_checks_cancellation_between_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / "a.txt").write_bytes(b"first")
    (source / "b.txt").write_bytes(b"second")
    importer = LocalSourceImporter(SourceStore(tmp_path / "store"), source.parent)
    snapshot = importer.acquire("sample", uuid4(), 1, SourceLimits(), threading.Event())
    stop = threading.Event()
    monitor = ProcessRunner(tmp_path, SourceLimits(), stop)
    original = Path.read_bytes
    reads: list[Path] = []

    def read(path: Path) -> bytes:
        if path.parent.name == "blobs":
            reads.append(path)
            stop.set()
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(SourceRejected, match="SOURCE_CANCELLED"):
        importer.store.validate(snapshot, monitor)
    assert len(reads) == 1
