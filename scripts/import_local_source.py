"""Create a source snapshot from a quiescent operator-owned import directory.

This command does not submit a public API job or mark an index ready.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from reposcope.adapters.source_storage import LocalSourceImporter, SourceStore  # noqa: E402
from reposcope.domain.source import SourceLimits, SourceRejected  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--name", required=True, help="One directory name under the import root")
    arguments = parser.parse_args(argv)
    try:
        importer = LocalSourceImporter(SourceStore(arguments.source_root), arguments.import_root)
        snapshot = importer.acquire(arguments.name, uuid4(), 1, SourceLimits(), threading.Event())
    except SourceRejected as error:
        print(f"FAIL: {error.code}", file=sys.stderr)
        return 1
    except OSError:
        print("FAIL: SOURCE_FILESYSTEM_UNAVAILABLE", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "snapshot_created",
                "storage_key": snapshot.storage_key,
                "manifest_digest": snapshot.digest,
                "file_count": len(snapshot.manifest.files),
                "eligible_bytes": snapshot.manifest.eligible_bytes,
                "skipped": snapshot.manifest.skipped,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
