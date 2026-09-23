"""Pure source boundary rules, independent of networking and Git execution."""

from __future__ import annotations

import pytest

from reposcope.domain.source import (
    SourceLimits,
    SourceRejected,
    canonical_repository,
    classify_content,
    classify_path,
    public_address,
    safe_relative_path,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://user:password@github.com/a/b",
        "https://github.com:443/a/b",
        "https://github.com/a/b?token=x",
        "https://github.com/a/..",
        "https://github.com/a/.",
        "https://github.com/a/b.git",
        "https://github.com.evil.test/a/b",
        "file:///etc/passwd",
        "D:/private",
        "https://github.com/a/b#main",
        "https://github.com/a/%2e%2e",
    ],
)
def test_repository_identity_rejects_transport_and_alias_ambiguity(url: str) -> None:
    with pytest.raises(SourceRejected):
        canonical_repository(url)


def test_public_repository_identity_preserves_canonical_source() -> None:
    assert (
        canonical_repository("https://github.com/pallets/itsdangerous")
        == "https://github.com/pallets/itsdangerous"
    )


@pytest.mark.parametrize(
    "path",
    [
        "../file",
        "a/../file",
        "/root/file",
        "C:/file",
        "a\\file",
        "//server/file",
        "a//file",
        "a/./file",
        "a\x00b",
        "a\nfile",
        "file:stream",
        "CON",
        "aux.txt",
        "dir/LPT1.py",
        "dir/name.",
        "dir/name ",
        "dir/.GIT/config",
        "a/",
    ],
)
def test_cross_platform_path_containment(path: str) -> None:
    with pytest.raises(SourceRejected):
        safe_relative_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.example",
        "config/.env.production",
        ".ssh/id_ed25519",
        "id_rsa",
        "config/private.key",
        "config/server.pem",
        "config/credentials.ini",
        "config/credentials.toml",
        "id_ed25519_sk",
        "keys/server.pem.bak",
        ".docker/config.json",
        ".config/gcloud/application_default_credentials.json",
        ".npmrc",
        ".credentials.json",
        ".secrets.yaml",
        ".npmrc.bak",
        ".netrc.old",
        "credentials.json",
        ".netrc",
    ],
)
def test_secret_paths_are_excluded_before_opening_content(path: str) -> None:
    assert classify_path(path) == "secret"


def test_policy_reports_exclusions_without_hiding_safe_source() -> None:
    assert classify_path("vendor/pkg.py") == "generated"
    assert classify_path("node_modules/pkg/index.ts") == "generated"
    assert classify_path("assets/logo.png") == "binary"
    assert classify_path("src/security.py") is None
    assert classify_content(b"print('hello')\n") is None
    assert classify_content(b"hello\x00binary") == "binary"
    assert classify_content(bytes([1, 2, 3, 4])) == "binary"
    assert classify_content(b"text\twith\nnormal\r\nwhitespace") is None
    assert classify_content(b"\xff") == "non_utf8"
    assert (
        classify_content(b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")
        == "lfs_pointer"
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "100.64.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:8.8.8.8",
        "fec0::1",
        "2002:7f00:1::",
        "64:ff9b::7f00:1",
        "2001:4860:4860::8888%eth0",
        "invalid",
    ],
)
def test_non_public_network_destinations_are_rejected(address: str) -> None:
    with pytest.raises(SourceRejected):
        public_address(address)


def test_resource_limits_are_explicit_and_can_only_be_lowered() -> None:
    defaults = SourceLimits()
    assert defaults.file_bytes == 1024 * 1024
    assert defaults.file_count == 20000
    assert defaults.source_bytes == 250 * 1024 * 1024
    assert defaults.disk_bytes == 1024 * 1024 * 1024
    assert defaults.deadline_seconds == 120
    assert public_address("8.8.8.8") == "8.8.8.8"
    assert SourceLimits(file_count=1).file_count == 1
    for invalid in (0, -1, 20001):
        with pytest.raises(ValueError):
            SourceLimits(file_count=invalid)
