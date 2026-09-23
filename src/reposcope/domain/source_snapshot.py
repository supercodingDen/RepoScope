"""Reproducible source metadata, containing no imported content or host paths."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class SourceLicense:
    path: str
    sha256: str
    identifier: str = "unknown"


@dataclass(frozen=True, slots=True)
class SourceManifest:
    source: str
    commit_sha: str | None
    files: tuple[SourceFile, ...]
    skipped: dict[str, int]
    scanned_entries: int
    eligible_bytes: int
    licenses: tuple[SourceLicense, ...]
    policy_version: str = "source-v1"

    def serialize(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.serialize().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    manifest: SourceManifest
    storage_key: str
    file_index: frozenset[SourceFile] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_index", frozenset(self.manifest.files))

    @property
    def digest(self) -> str:
        return self.manifest.digest
