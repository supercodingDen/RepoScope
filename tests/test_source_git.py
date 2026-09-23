"""Git metadata selection and opt-in production public-source acquisition."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from reposcope.adapters.source_git import GitSource, choose_revision, isolated_environment
from reposcope.adapters.source_storage import SourceStore
from reposcope.domain.source import SourceLimits, SourceRejected


def test_ambiguous_reference_rejected() -> None:
    data = ("a" * 40 + "\trefs/heads/release\n" + "b" * 40 + "\trefs/tags/release\n").encode()
    with pytest.raises(SourceRejected, match="SOURCE_REF_AMBIGUOUS"):
        choose_revision("release", data)


def test_annotated_tag_uses_peeled_commit() -> None:
    data = ("a" * 40 + "\trefs/tags/v1\n" + "b" * 40 + "\trefs/tags/v1^{}\n").encode()
    assert choose_revision("v1", data) == "b" * 40


def test_git_environment_does_not_inherit_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted")
    monkeypatch.setenv("GITHUB_TOKEN", "never-inherit")
    environment = isolated_environment(tmp_path, Path(os.__file__).resolve())
    assert "GIT_CONFIG_COUNT" not in environment
    assert "HTTPS_PROXY" not in environment
    assert "GITHUB_TOKEN" not in environment
    assert environment["GIT_NO_LAZY_FETCH"] == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("REPOSCOPE_TEST_PUBLIC_SOURCE") != "1",
    reason="Explicit public-source network gate",
)
def test_real_public_source(tmp_path: Path) -> None:
    binary = Path(os.environ["REPOSCOPE_GIT_BINARY"])
    source = GitSource(binary, SourceStore(tmp_path / "store"))
    job = uuid4()
    with source.session(
        "https://github.com/pallets/itsdangerous", job, 1, SourceLimits(), threading.Event()
    ) as session:
        commit = session.resolve("HEAD")
        assert len(commit) == 40
        snapshot = session.acquire(commit)
        assert snapshot.manifest.commit_sha == commit
        assert snapshot.manifest.files
        assert snapshot.manifest.licenses
        source.store.validate(snapshot)
    with source.session(
        "https://github.com/pallets/itsdangerous", job, 2, SourceLimits(), threading.Event()
    ) as retry:
        again = retry.acquire(commit)
        assert again.digest == snapshot.digest
    print("PUBLIC_SOURCE_PIN=" + commit)
    print("PUBLIC_SOURCE_MANIFEST=" + snapshot.digest)
    print("PUBLIC_SOURCE_FILES=" + str(len(snapshot.manifest.files)))


@pytest.fixture
def trusted_git() -> Path:
    value = os.environ.get("REPOSCOPE_GIT_BINARY")
    if not value:
        pytest.skip("Trusted Git fixture binary must be supplied explicitly")
    return Path(value)


def test_actual_git_objects_never_run_attributes_hooks_or_secret_blobs(
    tmp_path: Path, trusted_git: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = GitSource(trusted_git, SourceStore(tmp_path / "store"))
    with backend.session(
        "https://github.com/example/fixture", uuid4(), 1, SourceLimits(), threading.Event()
    ) as session:
        marker = tmp_path / "executed"
        fixtures = {
            "hello.py": b"answer = 42\n",
            ".env": b"synthetic forbidden fixture",
            ".gitconfig": b"[alias]\n pwn = !echo hostile\n",
            ".gitattributes": b"*.py filter=hostile diff=hostile\n",
            ".gitmodules": b'[submodule "bad"]\n url = https://evil.invalid/a\n',
            "id_rsa": b"synthetic forbidden key fixture",
            "pointer.txt": b"version https://git-lfs.github.com/spec/v1\noid sha256:fake\n",
            "binary.txt": b"binary\x00data",
            "LICENSE": b"Unrecognized test license",
            "escape": b"../../outside",
        }
        entries = []
        for name, content in fixtures.items():
            oid = session.git(["hash-object", "-w", "--stdin"], data=content).decode().strip()
            session.allowed_blobs.add(oid)
            mode = "120000" if name == "escape" else "100644"
            entries.append(f"{mode} blob {oid}\t{name}\n")
        tree = session.git(["mktree"], data="".join(entries).encode()).decode().strip()
        session.environment.update(
            {
                "GIT_AUTHOR_NAME": "Synthetic Fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            }
        )
        commit = session.git(["commit-tree", tree], data=b"Synthetic fixture\n").decode().strip()
        # The hostile filter/hook live only in synthetic fixture data; no checkout occurs.
        (session.git_dir / "hooks").mkdir()
        (session.git_dir / "hooks" / "post-checkout").write_text("#!/bin/sh\ntouch " + str(marker))
        original = session.git
        opened: list[str] = []

        def fixture_git(
            arguments: list[str],
            *,
            network: bool = False,
            repository: bool = True,
            data: bytes = b"",
        ) -> bytes:
            if network:
                return b""
            if arguments[:2] == ["cat-file", "blob"]:
                opened.append(arguments[2])
            return original(arguments, network=False, repository=repository, data=data)

        def fixture_fetch(sha: str, filter_spec: str) -> None:
            assert sha == commit and filter_spec == "blob:none"

        monkeypatch.setattr(session, "git", fixture_git)
        monkeypatch.setattr(session, "_fetch", fixture_fetch)
        snapshot = session.acquire(commit)
        paths = {file.path for file in snapshot.manifest.files}
        assert paths == {"hello.py", ".gitattributes", "LICENSE"}
        assert snapshot.manifest.skipped == {
            "binary": 1,
            "lfs_pointer": 1,
            "metadata": 2,
            "secret": 2,
            "symlink": 1,
        }
        for name in (".env", "id_rsa", ".gitconfig", ".gitmodules", "escape"):
            secret_oid = original(["hash-object", "--stdin"], data=fixtures[name]).decode().strip()
            assert secret_oid not in opened
        assert not marker.exists()


def test_actual_git_unrequested_blob_fails_closed(tmp_path: Path, trusted_git: Path) -> None:
    backend = GitSource(trusted_git, SourceStore(tmp_path / "store"))
    with backend.session(
        "https://github.com/example/fixture", uuid4(), 1, SourceLimits(), threading.Event()
    ) as session:
        session.git(["hash-object", "-w", "--stdin"], data=b"unexpected synthetic blob")
        with pytest.raises(SourceRejected, match="SOURCE_FILTER_VIOLATION"):
            session._objects()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("REPOSCOPE_TEST_PUBLIC_SOURCE") != "1", reason="Explicit real network quota gate"
)
def test_real_git_transport_quota_removes_partial_state(tmp_path: Path, trusted_git: Path) -> None:
    backend = GitSource(trusted_git, SourceStore(tmp_path / "store"))
    with pytest.raises(SourceRejected, match="SOURCE_DOWNLOAD_LIMIT"):
        with backend.session(
            "https://github.com/pallets/itsdangerous",
            uuid4(),
            1,
            SourceLimits(download_bytes=128),
            threading.Event(),
        ) as session:
            session.resolve("HEAD")
    assert list((backend.store.root / "attempts").iterdir()) == []
