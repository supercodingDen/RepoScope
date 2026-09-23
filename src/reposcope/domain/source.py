"""Pure, platform-independent source identity and resource boundary rules."""

from __future__ import annotations

import ipaddress
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

type SkipReason = Literal[
    "secret",
    "generated",
    "binary",
    "non_utf8",
    "lfs_pointer",
    "oversized",
    "symlink",
    "submodule",
    "metadata",
]

_REPOSITORY = re.compile(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}")
_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³]|conin\$|conout\$)(?:\..*)?")
_SECRET_NAMES = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".git-credentials",
        "credentials",
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        ".dockercfg",
    }
)
_SECRET_DIRECTORIES = frozenset(
    {".ssh", ".aws", ".azure", ".gcloud", ".gnupg", ".docker", ".kube", ".config"}
)
_SECRET_SUFFIXES = frozenset(
    {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".p8", ".ppk", ".tfvars", ".tfstate"}
)
_GENERATED_DIRECTORIES = frozenset(
    {
        "vendor",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "target",
        ".next",
        "__pycache__",
        "coverage",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)
_GENERATED_NAMES = frozenset(
    {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}
)
_BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".xz",
        ".7z",
        ".rar",
        ".jar",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".class",
        ".so",
        ".dll",
        ".exe",
        ".pyd",
        ".pyc",
        ".pyo",
        ".mp3",
        ".mp4",
        ".wav",
        ".mov",
        ".sqlite",
        ".db",
        ".parquet",
    }
)


class SourceRejected(Exception):
    """A safe bounded reason; never retains source bytes or command diagnostics."""

    def __init__(self, code: str) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) is None:
            raise ValueError("Invalid source failure code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SourceLimits:
    """Reviewed upper bounds; tests/operators may select smaller budgets."""

    file_bytes: int = 1024 * 1024
    file_count: int = 20000
    source_bytes: int = 250 * 1024 * 1024
    disk_bytes: int = 1024 * 1024 * 1024
    download_bytes: int = 250 * 1024 * 1024
    entry_count: int = 100000
    output_bytes: int = 16 * 1024 * 1024
    deadline_seconds: float = 120.0
    poll_seconds: float = 0.05

    def __post_init__(self) -> None:
        for value, ceiling in (
            (self.file_bytes, 1024 * 1024),
            (self.file_count, 20000),
            (self.source_bytes, 250 * 1024 * 1024),
            (self.disk_bytes, 1024 * 1024 * 1024),
            (self.download_bytes, 250 * 1024 * 1024),
            (self.entry_count, 100000),
            (self.output_bytes, 16 * 1024 * 1024),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
                raise ValueError(
                    "Source resource limits must be positive and within reviewed bounds"
                )
        if not math.isfinite(self.deadline_seconds) or not 0 < self.deadline_seconds <= 120:
            raise ValueError("Source deadline must be at most 120 seconds")
        if not math.isfinite(self.poll_seconds) or not 0.01 <= self.poll_seconds <= 0.1:
            raise ValueError("Source monitor interval must be between 10 and 100 milliseconds")


def canonical_repository(value: str) -> str:
    """Accept one public repository identity, not an arbitrary transport URL."""
    if _REPOSITORY.fullmatch(value) is None:
        raise SourceRejected("INVALID_SOURCE_URL")
    name = value.rsplit("/", 1)[1]
    if name in {".", ".."} or name.casefold().endswith(".git"):
        raise SourceRejected("INVALID_SOURCE_URL")
    return value


def safe_relative_path(value: str) -> str:
    """Validate original spelling before any normalization or filesystem access."""
    try:
        length = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise SourceRejected("UNSAFE_SOURCE_PATH") from None
    parts = value.split("/")
    if not 1 <= length <= 1024 or len(parts) > 32:
        raise SourceRejected("UNSAFE_SOURCE_PATH")
    for part in parts:
        if (
            part in {"", ".", ".."}
            or part.casefold() == ".git"
            or part.endswith((".", " "))
            or len(part.encode("utf-8")) > 255
            or _DEVICE.fullmatch(part.casefold()) is not None
            or any(
                char in '\\:<>"|?*'
                or ord(char) < 32
                or 127 <= ord(char) < 160
                or unicodedata.category(char) == "Cf"
                for char in part
            )
        ):
            raise SourceRejected("UNSAFE_SOURCE_PATH")
    return value


def classify_path(value: str) -> SkipReason | None:
    """Exclude sensitive/generated paths before requesting or reading their content."""
    safe_relative_path(value)
    parts = tuple(part.casefold() for part in value.split("/"))
    name = parts[-1]
    suffix = PurePosixPath(name).suffix
    if (
        any(part.startswith(".env") for part in parts)
        or any(part in _SECRET_DIRECTORIES for part in parts)
        or any(
            name.lstrip(".") == secret.lstrip(".")
            or any(
                name.lstrip(".").startswith(secret.lstrip(".") + marker)
                for marker in (".", "~", "-", "_")
            )
            for secret in _SECRET_NAMES
        )
        or any(part in _SECRET_SUFFIXES for part in PurePosixPath(name).suffixes)
        or re.fullmatch(r"(?:credentials?|secrets?)(?:[._-].*)?", name.lstrip(".")) is not None
        or name.startswith(("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"))
    ):
        return "secret"
    if any(part in _GENERATED_DIRECTORIES for part in parts[:-1]) or name in _GENERATED_NAMES:
        return "generated"
    if name in {".gitmodules", ".gitconfig"}:
        return "metadata"
    if suffix in _BINARY_SUFFIXES:
        return "binary"
    return None


def classify_content(value: bytes) -> SkipReason | None:
    """Classify already size-bounded, path-approved content without executing it."""
    if b"\x00" in value:
        return "binary"
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return "non_utf8"
    if any(unicodedata.category(char) == "Cc" and char not in "\t\n\r\f" for char in decoded):
        return "binary"
    if value.partition(b"\n")[0].rstrip(b"\r") == b"version https://git-lfs.github.com/spec/v1":
        return "lfs_pointer"
    return None


def public_address(value: str) -> str:
    """Reject non-public targets including IPv4-mapped IPv6 ambiguities."""
    if "%" in value:
        raise SourceRejected("UNSAFE_SOURCE_ADDRESS")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise SourceRejected("UNSAFE_SOURCE_ADDRESS") from None
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or isinstance(address, ipaddress.IPv6Address)
        and (
            address.ipv4_mapped is not None
            or address.is_site_local
            or address.sixtofour is not None
            or address.teredo is not None
        )
    ):
        raise SourceRejected("UNSAFE_SOURCE_ADDRESS")
    return str(address)
