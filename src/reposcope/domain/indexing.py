"""Pure, versioned source chunking primitives for T06."""

from __future__ import annotations

import hashlib
import math
import re
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Literal

import tiktoken
import tree_sitter_python
import tree_sitter_typescript
from tiktoken import Encoding
from tree_sitter import Language, Node, Parser

ParseMode = Literal["ast", "syntax-fallback", "language-fallback"]


@dataclass(frozen=True, slots=True)
class IndexChunk:
    path: str
    ordinal: int
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    text: str
    sha256: str
    token_count: int
    language: str
    symbol: str | None


def embedding_input(chunk: IndexChunk) -> str:
    """Versioned text submitted to the embedding space and used as its cache identity."""
    return (
        f"path:{chunk.path}\nlanguage:{chunk.language}\nsymbol:{chunk.symbol or '-'}\n{chunk.text}"
    )


@dataclass(frozen=True, slots=True)
class ChunkedFile:
    path: str
    language: str
    parse_mode: ParseMode
    dependencies: tuple[str, ...]
    chunks: tuple[IndexChunk, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    provider: str
    model: str
    dimensions: int
    version: str


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    inputs: tuple[str, ...]
    token_counts: tuple[int, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.inputs) <= 32 or len(self.inputs) != len(self.token_counts):
            raise ValueError("Embedding batch must contain 1 to 32 matching inputs")
        if any(
            not value or not 0 < count <= 800
            for value, count in zip(self.inputs, self.token_counts, strict=True)
        ):
            raise ValueError("Embedding inputs require positive bounded tokens")
        if sum(self.token_counts) > 20_000:
            raise ValueError("Embedding batch exceeds 20,000 tokens")


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    space: EmbeddingSpace
    vectors: tuple[tuple[float, ...], ...]


def validate_embedding_response(
    batch: EmbeddingBatch, space: EmbeddingSpace, vectors: tuple[tuple[float, ...], ...]
) -> EmbeddingResponse:
    """Validate provider vectors before persistence."""
    if space.dimensions != 384 or len(vectors) != len(batch.inputs):
        raise ValueError("Embedding response dimensions or count mismatch")
    normalized: list[tuple[float, ...]] = []
    for vector in vectors:
        if len(vector) != space.dimensions:
            raise ValueError("Embedding response dimensions or count mismatch")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Embedding response contains non-finite values")
        norm = math.sqrt(math.fsum(value * value for value in vector))
        if not math.isfinite(norm) or norm == 0:
            raise ValueError("Embedding response contains zero or non-finite vector")
        normalized.append(tuple(value / norm for value in vector))
    return EmbeddingResponse(space, tuple(normalized))


PARSER_VERSION = "tree-sitter-2026-09-v1"
TOKENIZER_VERSION = "cl100k_base-v1"
CHUNK_POLICY_VERSION = "ast-600-800-0-v1"
TARGET_TOKENS = 600
MAX_TOKENS = 800
MAX_DEPENDENCIES = 64


@lru_cache(maxsize=1)
def _encoding() -> Encoding:
    return tiktoken.get_encoding("cl100k_base")


def _language(path: str) -> str:
    suffix = PurePosixPath(path).suffix.casefold()
    return {".py": "python", ".ts": "typescript", ".tsx": "tsx"}.get(suffix, "text")


def _parser(language: str) -> Parser:
    grammar = {
        "python": tree_sitter_python.language,
        "typescript": tree_sitter_typescript.language_typescript,
        "tsx": tree_sitter_typescript.language_tsx,
    }[language]
    return Parser(Language(grammar()))


def _symbol(node: Node, content: bytes) -> str | None:
    definition: Node | None = node
    if node.type == "decorated_definition":
        definition = node.child_by_field_name("definition")
    elif node.type == "export_statement":
        definition = next(
            (child for child in node.named_children if child.type.endswith("declaration")), None
        )
    if definition is None:
        return None
    if definition.type not in {
        "function_definition",
        "class_definition",
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
    }:
        return None
    name = definition.child_by_field_name("name")
    if name is None or name.end_byte - name.start_byte > 128:
        return None
    return content[name.start_byte : name.end_byte].decode("utf-8")


def _segments(
    language: str, content: bytes
) -> tuple[ParseMode, tuple[tuple[int, int, str | None], ...]]:
    if language == "text":
        return "language-fallback", ((0, len(content), None),)
    root = _parser(language).parse(content).root_node
    if root.has_error:
        return "syntax-fallback", ((0, len(content), None),)
    nodes = root.named_children
    if not nodes:
        return "ast", ((0, len(content), None),) if content else ()
    segments: list[tuple[int, int, str | None]] = []
    start = 0
    for index, node in enumerate(nodes):
        end = len(content) if index == len(nodes) - 1 else node.end_byte
        if end > start:
            segments.append((start, end, _symbol(node, content)))
        start = end
    return "ast", tuple(segments)


def _dependencies(language: str, content: str) -> tuple[str, ...]:
    if language == "python":
        matches = re.finditer(
            r"(?m)^\s*(?:from\s+([\w.]+)\s+import\s+|import\s+([\w., ]+))", content
        )
        values = [match.group(1) or match.group(2).split(",", 1)[0].strip() for match in matches]
    elif language in {"typescript", "tsx"}:
        values = re.findall(
            r"(?m)^\s*import\s+(?:[^\n]*?\s+from\s+)?['\"]([^'\"\n]{1,256})['\"]",
            content,
        )
    else:
        values = []
    return tuple(dict.fromkeys(value[:256] for value in values if value))[:MAX_DEPENDENCIES]


def _line(line_breaks: tuple[int, ...], byte_offset: int) -> int:
    return bisect_left(line_breaks, byte_offset) + 1


def _chunk_segment(
    path: str,
    language: str,
    symbol: str | None,
    content: bytes,
    line_breaks: tuple[int, ...],
    start: int,
    end: int,
    ordinal: int,
    check_time: Callable[[], None] | None,
) -> tuple[IndexChunk, ...]:
    if check_time is not None:
        check_time()
    encoder = _encoding()
    prefix = f"path:{path}\nlanguage:{language}\nsymbol:{symbol or '-'}\n"
    overhead = len(encoder.encode(prefix, disallowed_special=()))
    if overhead >= TARGET_TOKENS:
        raise ValueError("Chunk path or metadata exceeds the token budget")
    source = content[start:end].decode("utf-8")
    token_bytes = [
        encoder.decode_single_token_bytes(token)
        for token in encoder.encode(source, disallowed_special=())
    ]
    byte_positions = [0]
    for token in token_bytes:
        byte_positions.append(byte_positions[-1] + len(token))
    if byte_positions[-1] != end - start:
        raise ValueError("Tokenizer did not preserve source bytes")
    chunks: list[IndexChunk] = []
    position = 0
    target = TARGET_TOKENS - overhead
    while position < len(token_bytes):
        if check_time is not None:
            check_time()
        stop = min(len(token_bytes), position + target)
        while stop > position:
            part = content[start + byte_positions[position] : start + byte_positions[stop]]
            try:
                text = part.decode("utf-8")
            except UnicodeDecodeError:
                stop -= 1
                continue
            count = len(encoder.encode(prefix + text, disallowed_special=()))
            if count <= MAX_TOKENS:
                break
            stop -= 1
        if stop == position:
            raise ValueError("No valid UTF-8 chunk boundary within the token budget")
        first = start + byte_positions[position]
        last = start + byte_positions[stop]
        end_line = _line(line_breaks, last - 1) if last > first else _line(line_breaks, last)
        chunks.append(
            IndexChunk(
                path=path,
                ordinal=ordinal + len(chunks),
                start_byte=first,
                end_byte=last,
                start_line=_line(line_breaks, first),
                end_line=end_line,
                text=text,
                sha256=hashlib.sha256(part).hexdigest(),
                token_count=count,
                language=language,
                symbol=symbol,
            )
        )
        position = stop
    return tuple(chunks)


def chunk_file(
    path: str, content: bytes, check_time: Callable[[], None] | None = None
) -> ChunkedFile:
    """Return deterministic chunks with exact original source spans."""
    decoded = content.decode("utf-8")
    language = _language(path)
    mode, segments = _segments(language, content)
    line_breaks = tuple(index for index, byte in enumerate(content) if byte == 10)
    chunks: list[IndexChunk] = []
    for start, end, symbol in segments:
        if check_time is not None:
            check_time()
        chunks.extend(
            _chunk_segment(
                path,
                language,
                symbol,
                content,
                line_breaks,
                start,
                end,
                len(chunks),
                check_time,
            )
        )
    return ChunkedFile(path, language, mode, _dependencies(language, decoded), tuple(chunks))
