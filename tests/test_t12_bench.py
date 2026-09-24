"""T12 corpus provenance and measurement invariants."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from bench.t12_archive import archive
from bench.t12_batches import batches
from bench.t12_corpus import corpus_files, fixed_queries, provenance
from bench.t12_load import validated_database_url
from bench.t12_measure import EF_SEARCH_VALUES, percentile, query_vector


def test_corpus_uses_distinct_eligible_source_without_reading_secret_paths(
    tmp_path: Path,
) -> None:
    lib, packages, tools = (tmp_path / name for name in ("lib", "packages", "tools"))
    for root in (lib, packages, tools):
        root.mkdir()
    (lib / "module.py").write_text("def solve_problem():\n    return 42\n", encoding="utf-8")
    (lib / "secret.py").write_text("def forbidden():\n    return 1\n", encoding="utf-8")
    files = list(corpus_files(lib, packages, tools, target_chunks=1))
    assert len(files) == 1
    assert files[0].path == "cpython/module.py"
    assert files[0].chunks[0].chunk.text.startswith("def solve_problem")
    assert provenance(files)["chunks"] == len(files[0].chunks)


def test_fixed_queries_are_deterministic_and_require_distinct_symbols(tmp_path: Path) -> None:
    lib, packages, tools = (tmp_path / name for name in ("lib", "packages", "tools"))
    for root in (lib, packages, tools):
        root.mkdir()
    (lib / "module.py").write_text(
        "def alpha_function():\n    return 1\n\ndef beta_function():\n    return 2\n",
        encoding="utf-8",
    )
    files = list(corpus_files(lib, packages, tools, target_chunks=1))
    first = fixed_queries(files, count=2)
    assert first == fixed_queries(files, count=2)
    assert len({item["query"] for item in first}) == 2
    with pytest.raises(ValueError, match="distinct symbols"):
        fixed_queries(files, count=3)


def test_nearest_rank_and_mock_query_vector() -> None:
    assert percentile([4.0, 2.0, 3.0, 1.0], 0.5) == 2.0
    assert len(query_vector("Where is alpha_function implemented?").strip("[]").split(",")) == 384
    with pytest.raises(ValueError, match="requires observations"):
        percentile([])


def test_batch_packing_respects_item_and_token_ceilings() -> None:
    packed = batches([("source", 700)] * 40, 32)
    assert [len(item.inputs) for item in packed] == [28, 12]
    assert all(sum(item.token_counts) <= 20_000 for item in packed)
    with pytest.raises(ValueError, match="Batch limit"):
        batches([("source", 1)], 33)


def test_ef_search_sweep_stays_within_pgvector_limits() -> None:
    assert EF_SEARCH_VALUES[:4] == (40, 80, 120, 200)
    assert all(1 <= value <= 1000 for value in EF_SEARCH_VALUES)


def test_raw_archive_is_deterministic_and_allowlisted(tmp_path: Path) -> None:
    (tmp_path / "one.json").write_text('{"count": 1}\n', encoding="utf-8")
    first = archive(tmp_path, ("one.json",))
    assert archive(tmp_path, ("one.json",))["archive_sha256"] == first["archive_sha256"]
    with ZipFile(tmp_path / "t12-raw-evidence.zip") as result:
        assert result.namelist() == ["one.json"]
        assert result.read("one.json") == (tmp_path / "one.json").read_bytes()
    with pytest.raises(ValueError, match="plain JSON basenames"):
        archive(tmp_path, ("../outside.json",))
    assert (tmp_path / "t12-raw-evidence.zip").is_file()


def test_loader_requires_explicit_disposable_loopback_database() -> None:
    url = "postgresql://reposcope_migrator@127.0.0.1:15432/reposcope"
    assert validated_database_url({"T12_DATABASE_URL": url, "T12_DISPOSABLE_DATABASE": "1"}) == url
    with pytest.raises(ValueError, match="disposable"):
        validated_database_url({"T12_DATABASE_URL": url})
    with pytest.raises(ValueError, match="loopback"):
        validated_database_url(
            {"T12_DATABASE_URL": url.replace(":15432", ":5432"), "T12_DISPOSABLE_DATABASE": "1"}
        )
