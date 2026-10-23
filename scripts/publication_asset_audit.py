"""Inspect release image layers without exposing scanner matches."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

_BLOB_NAME = re.compile(r"[0-9a-f]{64}")
_MAX_LAYERS = 500
_MAX_LAYER_BYTES = 8 * 1024**3


@dataclass(frozen=True)
class ArchiveScanSummary:
    layer_count: int
    opaque_findings: int


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


def extract_and_classify(archive: Path, report: Path, destination: Path) -> ArchiveScanSummary:
    """Extract every layer and classify only raw matches on opaque layer blobs."""
    findings: object = json.loads(report.read_text(encoding="utf-8"))
    if not isinstance(findings, list):
        raise ValueError("Invalid release scan report")
    destination.mkdir(parents=True, exist_ok=False)
    layer_blobs: set[str] = set()
    blob_metadata: dict[str, tuple[str, int]] = {}
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
                    continue
                layer_count += 1
                layer_bytes += member.size
                if layer_count > _MAX_LAYERS or layer_bytes > _MAX_LAYER_BYTES:
                    raise ValueError("Release layer limit exceeded")
                _copy_layer(source, header, destination / f"{layer_count:03d}.{kind}")
                layer_blobs.add(name)
    if layer_count == 0:
        raise ValueError("No Docker layers found")
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
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get("File"), str):
            raise ValueError("Invalid release scan finding")
        file_name = finding["File"]
        blob = file_name.rsplit("/", 1)[-1]
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
    return ArchiveScanSummary(layer_count, opaque_findings)


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
                "No Docker layers found",
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
        f"{summary.opaque_findings} raw layer-byte matches require extracted-layer review."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
