"""Static imports resolve only to files in the pinned manifest."""

from reposcope.domain.dependency import resolve_one_hop
from reposcope.domain.indexing import chunk_file


def test_python_and_typescript_imports_resolve_within_manifest() -> None:
    paths = frozenset(
        {"pkg/main.py", "pkg/helpers.py", "pkg/sub/__init__.py", "web/main.ts", "web/lib.tsx"}
    )
    assert resolve_one_hop("pkg/main.py", ("pkg.helpers", "pkg.sub", "os"), paths) == (
        "pkg/helpers.py",
        "pkg/sub/__init__.py",
    )
    assert resolve_one_hop("web/main.ts", ("./lib", "react", "../../secret"), paths) == (
        "web/lib.tsx",
    )


def test_imports_cannot_escape_or_follow_second_hop() -> None:
    paths = frozenset({"src/main.ts", "src/a.ts", "b.ts", "src/a/helper.ts"})
    assert resolve_one_hop("src/main.ts", ("../../b", "./a", "./a/helper"), paths) == (
        "src/a.ts",
        "src/a/helper.ts",
    )


def test_python_relative_from_import_preserves_imported_name() -> None:
    metadata = chunk_file("pkg/main.py", b"from . import helpers\n")
    assert metadata.dependencies == (".helpers",)
    assert resolve_one_hop(
        "pkg/main.py", metadata.dependencies, frozenset({"pkg/main.py", "pkg/helpers.py"})
    ) == ("pkg/helpers.py",)
