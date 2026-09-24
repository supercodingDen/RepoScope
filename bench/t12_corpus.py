"""Build a reproducible, source-only scale corpus without executing imported code."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from reposcope.domain.indexing import IndexChunk, chunk_file
from reposcope.domain.source import SourceRejected, classify_content, classify_path


@dataclass(frozen=True, slots=True)
class CorpusChunk:
    path: str
    language: str
    chunk: IndexChunk


@dataclass(frozen=True, slots=True)
class CorpusFile:
    path: str
    language: str
    parse_mode: str
    digest: str
    byte_count: int
    chunks: tuple[CorpusChunk, ...]


def source_paths(
    python_lib: Path, site_packages: Path, python_tools: Path
) -> Iterator[tuple[str, Path]]:
    """Yield each Python source once in stable order from two pinned installations."""
    for label, root in (
        ("cpython", python_lib),
        ("packages", site_packages),
        ("cpython-tools", python_tools),
    ):
        if not root.is_dir():
            raise ValueError(f"Missing {label} source root")
        for source in sorted(root.rglob("*.py")):
            if source.is_symlink() or not source.is_file():
                continue
            relative = source.relative_to(root).as_posix()
            name = f"{label}/{relative}"
            try:
                if classify_path(name) is None and source.stat().st_size <= 1024 * 1024:
                    yield name, source
            except (OSError, SourceRejected):
                continue


def corpus_files(
    python_lib: Path, site_packages: Path, python_tools: Path, *, target_chunks: int = 100_000
) -> Iterator[CorpusFile]:
    """Yield real, distinct source files until the requested chunk count is met."""
    if target_chunks < 1:
        raise ValueError("target_chunks must be positive")
    count = 0
    for name, source in source_paths(python_lib, site_packages, python_tools):
        content = source.read_bytes()
        if classify_content(content) is not None:
            continue
        try:
            parsed = chunk_file(name, content)
        except (UnicodeDecodeError, ValueError):
            continue
        if not parsed.chunks:
            continue
        wrapped = tuple(CorpusChunk(name, parsed.language, chunk) for chunk in parsed.chunks)
        yield CorpusFile(
            name,
            parsed.language,
            parsed.parse_mode,
            hashlib.sha256(content).hexdigest(),
            len(content),
            wrapped,
        )
        count += len(wrapped)
        if count >= target_chunks:
            return
    raise ValueError(f"Only {count} eligible real chunks; target is {target_chunks}")


def fixed_queries(files: list[CorpusFile], *, count: int = 200) -> list[dict[str, str]]:
    """Select stable code-location questions from distinct real source symbols."""
    candidates: dict[str, tuple[str, str]] = {}
    for file in files:
        for item in file.chunks:
            symbol = item.chunk.symbol
            if symbol and symbol.isidentifier() and 3 <= len(symbol) <= 64:
                candidates.setdefault(symbol, (file.path, symbol))
    selected = sorted(
        candidates.values(), key=lambda item: hashlib.sha256(item[1].encode()).digest()
    )
    if len(selected) < count:
        raise ValueError(f"Only {len(selected)} distinct symbols; target is {count}")
    return [
        {"id": f"q{index:03d}", "query": f"Where is {symbol} implemented?", "source_path": path}
        for index, (path, symbol) in enumerate(selected[:count], start=1)
    ]


def provenance(files: list[CorpusFile]) -> dict[str, object]:
    """Record hashes and counts without redistributing imported source text."""
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.path.encode())
        digest.update(bytes.fromhex(file.digest))
    return {
        "source_fingerprint": digest.hexdigest(),
        "files": len(files),
        "chunks": sum(len(file.chunks) for file in files),
        "source_bytes": sum(file.byte_count for file in files),
        "sources": "CPython 3.12.14 Lib/Tools and uv.lock-installed public Python packages",
        "source_redistributed": False,
        "imported_code_executed": False,
        "embedding_space": "mock-sha256-384-l2-v1",
    }


def write_manifest(path: Path, files: list[CorpusFile]) -> None:
    """Write compact, reviewable provenance and fixed queries."""
    result = {"provenance": provenance(files), "queries": fixed_queries(files)}
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
