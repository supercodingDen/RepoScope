"""Create a deterministic archive of raw T12 observations for GitHub review."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ARCHIVE_FILES = (
    "t12-before.json",
    "t12-after-count.json",
    "t12-after-fts.json",
    "t12-hnsw-m64.json",
    "t12-hnsw-ip.json",
    "t12-final-search.json",
    "t12-final-pool10.json",
    "t12-final-420-pool10.json",
    "t12-unfiltered-420.json",
    "t12-filtered-cpython.json",
    "t12-filtered-sweep.json",
    "t12-health.json",
    "t12-batches.json",
    "t12-sql-plans.json",
    "t12-load.json",
    "t12-load-tuned.json",
)


def archive(data_dir: Path, names: tuple[str, ...] = ARCHIVE_FILES) -> dict[str, object]:
    """Archive only explicit benchmark artifacts, never source or environment files."""
    if any(name != Path(name).name or not name.endswith(".json") for name in names):
        raise ValueError("Archive entries must be plain JSON basenames")
    records: list[dict[str, object]] = []
    target = data_dir / "t12-raw-evidence.zip"
    with ZipFile(target, "w") as output:
        for name in names:
            raw = (data_dir / name).read_bytes()
            json.loads(raw)
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            output.writestr(info, raw, compress_type=ZIP_DEFLATED, compresslevel=9)
            records.append(
                {"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            )
    index: dict[str, object] = {
        "archive": target.name,
        "archive_bytes": target.stat().st_size,
        "archive_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "files": records,
    }
    (data_dir / "t12-raw-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return index


def main() -> None:
    """Write one reviewable raw-results archive and a checksum index."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    arguments = parser.parse_args()
    result = archive(arguments.data_dir)
    print(json.dumps({"archive_bytes": result["archive_bytes"], "files": len(ARCHIVE_FILES)}))


if __name__ == "__main__":
    main()
