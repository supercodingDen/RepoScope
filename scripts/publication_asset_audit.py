"""Inspect release image layers without exposing scanner matches."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO

_BLOB_NAME = re.compile(r"[0-9a-f]{64}")
_MAX_LAYERS = 500
_MAX_LAYER_BYTES = 8 * 1024**3
_MAX_LAYER_FILES = 250_000
# Public Python 3.12.14 release-signing key fingerprint from the pinned official image:
# https://github.com/docker-library/python/blob/688a0b86bb44289df16a363e9f41d90514c1a5f9/3.12/slim-bookworm/Dockerfile
_PYTHON_GPG_FINGERPRINT = b"7169605F62C751356D054A26A821E680E5FA6305"


@dataclass(frozen=True)
class ArchiveScanSummary:
    layer_count: int
    opaque_findings: int
    public_signing_key_findings: int


def _archive_kind(header: bytes) -> str | None:
    if header[257:262] == b"ustar":
        return "tar"
    if header.startswith(b"\x1f\x8b"):
        return "tar.gz"
    return None


def _copy_layer(source: IO[bytes], header: bytes, destination: Path) -> None:
    with destination.open("xb") as output:
        output.write(header)
        shutil.copyfileobj(source, output)


def _known_public_signing_key(blob: bytes, finding: dict[str, object]) -> bool:
    match_text = finding.get("Match")
    if (
        finding.get("RuleID") != "generic-api-key"
        or finding.get("Secret") != "REDACTED"
        or not isinstance(match_text, str)
        or re.fullmatch(r'GPG_KEY=REDACTED["\s,}\]]*', match_text) is None
    ):
        return False
    values = re.findall(rb"GPG_KEY=([A-Za-z0-9]+)", blob)
    return bool(values) and all(value == _PYTHON_GPG_FINGERPRINT for value in values)


def _extract_layer_files(destination: Path) -> None:
    """Stage regular files from every layer, including files later removed by whiteouts."""
    files_root = destination / "files"
    files_root.mkdir()
    file_count = 0
    file_bytes = 0
    for layer_path in sorted(destination.glob("*.tar*")):
        layer_root = files_root / layer_path.name.split(".", 1)[0]
        with tarfile.open(layer_path, mode="r:*") as layer:
            for member in layer:
                if not member.isfile():
                    continue
                name = member.name
                relative = PurePosixPath(name)
                if (
                    not name
                    or name.startswith("/")
                    or "\\" in name
                    or ":" in name
                    or ".." in relative.parts
                    or not relative.parts
                ):
                    raise ValueError("Unsafe release layer path")
                file_count += 1
                file_bytes += member.size
                if file_count > _MAX_LAYER_FILES or file_bytes > _MAX_LAYER_BYTES:
                    raise ValueError("Release layer file limit exceeded")
                source = layer.extractfile(member)
                if source is None:
                    raise ValueError("Unreadable release layer file")
                target = layer_root.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def extract_and_classify(archive: Path, report: Path, destination: Path) -> ArchiveScanSummary:
    """Extract every layer and classify only raw matches on opaque layer blobs."""
    findings: object = json.loads(report.read_text(encoding="utf-8"))
    if not isinstance(findings, list):
        raise ValueError("Invalid release scan report")
    destination.mkdir(parents=True, exist_ok=False)
    layer_blobs: set[str] = set()
    blob_metadata: dict[str, tuple[str, int]] = {}
    json_blobs: dict[str, bytes] = {}
    layer_count = 0
    layer_bytes = 0
    with tarfile.open(archive, mode="r:gz") as outer:
        for member in outer:
            if not member.isfile():
                continue
            name = member.name.rsplit("/", 1)[-1]
            if member.name != f"blobs/sha256/{name}" or not _BLOB_NAME.fullmatch(name):
                continue
            source = outer.extractfile(member)
            if source is None:
                raise ValueError("Unreadable release layer")
            with source:
                header = source.read(512)
                kind = _archive_kind(header)
                blob_metadata[name] = (
                    kind or ("json" if header.lstrip().startswith((b"{", b"[")) else "other"),
                    member.size,
                )
                if kind is None:
                    if blob_metadata[name][0] == "json" and member.size <= 1024**2:
                        json_blobs[name] = header + source.read()
                    continue
                layer_count += 1
                layer_bytes += member.size
                if layer_count > _MAX_LAYERS or layer_bytes > _MAX_LAYER_BYTES:
                    raise ValueError("Release layer limit exceeded")
                _copy_layer(source, header, destination / f"{layer_count:03d}.{kind}")
                layer_blobs.add(name)
    if layer_count == 0:
        raise ValueError("No Docker layers found")
    _extract_layer_files(destination)
    redacted_keys: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("Secret") != "REDACTED":
            continue
        match_text = finding.get("Match")
        if isinstance(match_text, str):
            match = re.search(r"\b([A-Z][A-Z0-9_]{2,59})=REDACTED\b", match_text)
            if match is not None:
                redacted_keys.add(match.group(1))
    opaque_findings = 0
    public_signing_key_findings = 0
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get("File"), str):
            raise ValueError("Invalid release scan finding")
        file_name = finding["File"]
        blob = file_name.rsplit("/", 1)[-1]
        if (
            archive.name in file_name
            and f"blobs/sha256/{blob}" in file_name
            and blob in json_blobs
            and _known_public_signing_key(json_blobs[blob], finding)
        ):
            public_signing_key_findings += 1
            continue
        if (
            archive.name not in file_name
            or f"blobs/sha256/{blob}" not in file_name
            or blob not in layer_blobs
        ):
            raise ValueError(
                "Unclassified release finding "
                f"(archive={int(archive.name in file_name)}, "
                f"blob_path={int(f'blobs/sha256/{blob}' in file_name)}, "
                f"known_layer={int(blob in layer_blobs)}, "
                f"blob_kind={blob_metadata.get(blob, ('missing', 0))[0]}, "
                f"blob_bytes={blob_metadata.get(blob, ('missing', 0))[1]}, "
                f"match_keys={','.join(sorted(redacted_keys)[:10]) or 'none'})"
            )
        opaque_findings += 1
    return ArchiveScanSummary(layer_count, opaque_findings, public_signing_key_findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        summary = extract_and_classify(args.archive, args.report, args.destination)
    except ValueError as error:
        reason = str(error)
        if not reason.startswith(
            (
                "Invalid release scan report",
                "Invalid release scan finding",
                "Unreadable release layer",
                "Release layer limit exceeded",
                "Release layer file limit exceeded",
                "No Docker layers found",
                "Unsafe release layer path",
                "Unreadable release layer file",
                "Unclassified release finding",
            )
        ):
            reason = "invalid archive data"
        print(f"Release archive classification failed ({reason}); publication remains blocked.")
        return 1
    except (OSError, tarfile.TarError, json.JSONDecodeError):
        print("Release archive classification failed (I/O error); publication remains blocked.")
        return 1
    print(
        f"Prepared {summary.layer_count} Docker layers; "
        f"{summary.opaque_findings} raw layer-byte matches require extracted-layer review; "
        f"{summary.public_signing_key_findings} matches use the pinned public signing fingerprint."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
