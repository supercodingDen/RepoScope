"""Contract tests for T06 source chunking."""

from __future__ import annotations

import hashlib

from reposcope.domain.indexing import chunk_file


def test_python_chunks_preserve_original_spans_and_symbols() -> None:
    content = b"import os\n\ndef alpha():\n    return os.name\n\ndef beta():\n    return 2\n"
    result = chunk_file("pkg/example.py", content)

    assert result.language == "python"
    assert result.parse_mode == "ast"
    assert "os" in result.dependencies
    assert result.chunks
    assert any(chunk.symbol == "alpha" for chunk in result.chunks)
    for chunk in result.chunks:
        assert chunk.text.encode("utf-8") == content[chunk.start_byte : chunk.end_byte]
        assert chunk.sha256 == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        assert 1 <= chunk.start_line <= chunk.end_line <= content.count(b"\n") + 1
        assert chunk.token_count <= 800


def test_syntax_error_and_unsupported_language_use_labeled_fallback() -> None:
    broken = chunk_file("bad.py", b"def broken(:\n    pass\n")
    other = chunk_file("main.go", b"package main\nfunc main() {}\n")

    assert broken.parse_mode == "syntax-fallback"
    assert other.parse_mode == "language-fallback"
    assert all(chunk.text for chunk in broken.chunks + other.chunks)


def test_long_line_respects_hard_token_limit_and_exact_bytes() -> None:
    content = (b"a" * 12000) + b"\n"
    result = chunk_file("long.txt", content)

    assert len(result.chunks) > 1
    assert all(0 < chunk.token_count <= 800 for chunk in result.chunks)
    assert all(
        chunk.text.encode("utf-8") == content[chunk.start_byte : chunk.end_byte]
        for chunk in result.chunks
    )
    assert result.chunks[0].start_byte == 0
    assert result.chunks[-1].end_byte == len(content)


def test_same_content_in_different_paths_keeps_distinct_locations() -> None:
    content = b"print('hello')\n"
    left = chunk_file("a.py", content)
    right = chunk_file("b.py", content)

    assert left.chunks[0].sha256 == right.chunks[0].sha256
    assert left.chunks[0].path != right.chunks[0].path


def test_typescript_import_and_utf8_split_keep_exact_locations() -> None:
    source = 'import { x } from "./module";\nexport function café() { return x; }\n'
    parsed = chunk_file("src/example.ts", source.encode("utf-8"))
    long = ("é" * 5000).encode("utf-8")
    split = chunk_file("docs/unicode.txt", long)

    assert parsed.parse_mode == "ast"
    assert parsed.dependencies == ("./module",)
    assert any(chunk.symbol == "café" for chunk in parsed.chunks)
    assert len(split.chunks) > 1
    assert all(
        chunk.text.encode("utf-8") == long[chunk.start_byte : chunk.end_byte]
        for chunk in split.chunks
    )
    assert split.chunks[0].start_byte == 0
    assert split.chunks[-1].end_byte == len(long)
