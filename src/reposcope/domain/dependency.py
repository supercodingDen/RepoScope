"""Resolve static import metadata against an immutable manifest file set."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath


def resolve_one_hop(path: str, imports: Iterable[str], allowed: frozenset[str]) -> tuple[str, ...]:
    """Return deterministic direct dependency paths; never consult the host filesystem."""
    suffix = PurePosixPath(path).suffix
    found: set[str] = set()
    for imported in imports:
        if not imported or "\\" in imported or imported.startswith("/"):
            continue
        base: str | None = None
        if suffix == ".py":
            if imported.startswith("."):
                # Python relative imports are supported only when their leading dots stay
                # inside the package path. Index metadata has no imported-symbol details.
                dots = len(imported) - len(imported.lstrip("."))
                parent = path.split("/")[:-1]
                if dots > len(parent):
                    continue
                parts = parent[: len(parent) - dots + 1]
                tail = imported[dots:]
                if tail:
                    parts.extend(tail.split("."))
            else:
                parts = imported.split(".")
            if not parts or any(not part.isidentifier() for part in parts):
                continue
            base = "/".join(parts)
            candidates: tuple[str, ...] = (base + ".py", base + "/__init__.py")
        elif suffix in {".ts", ".tsx"}:
            if not imported.startswith("./") and not imported.startswith("../"):
                continue
            parts = path.split("/")[:-1]
            escaped = False
            for part in imported.split("/"):
                if part in {"", "."}:
                    continue
                if part == "..":
                    if not parts:
                        escaped = True
                        break
                    parts.pop()
                else:
                    parts.append(part)
            if escaped or not parts:
                continue
            base = "/".join(parts)
            candidates = (
                base,
                base + ".ts",
                base + ".tsx",
                base + "/index.ts",
                base + "/index.tsx",
            )
        else:
            continue
        for candidate in candidates:
            if candidate in allowed and candidate != path:
                found.add(candidate)
                break
    return tuple(sorted(found))
