"""Offline import and parser ABI checks for the locked dependency set."""

import importlib

import pytest
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser


@pytest.mark.parametrize(
    "module",
    [
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic_settings",
        "psycopg",
        "psycopg_pool",
        "pgvector",
        "nats",
        "redis.asyncio",
        "httpx",
        "openai",
        "tiktoken",
        "prometheus_client",
    ],
)
def test_dependency_import(module: str) -> None:
    assert importlib.import_module(module) is not None


def test_python_parser_abi() -> None:
    parser = Parser(Language(tree_sitter_python.language()))
    tree = parser.parse(b"def add(a: int, b: int) -> int:\n    return a + b\n")
    assert not tree.root_node.has_error
    assert tree.root_node.children[0].type == "function_definition"


def test_typescript_parser_abi() -> None:
    parser = Parser(Language(tree_sitter_typescript.language_typescript()))
    tree = parser.parse(b"function add(a: number, b: number): number { return a + b; }")
    assert not tree.root_node.has_error


def test_tsx_parser_abi() -> None:
    parser = Parser(Language(tree_sitter_typescript.language_tsx()))
    tree = parser.parse(b"const View = () => <main>Hello</main>;")
    assert not tree.root_node.has_error
