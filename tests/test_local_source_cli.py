"""Operator CLI imports snapshots without exposing source or creating API jobs."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.import_local_source import main


def test_operator_import_reports_snapshot_not_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "imports" / "sample"
    source.mkdir(parents=True)
    (source / "hello.py").write_text("PRIVATE_TEST_CONTENT = 1", encoding="utf-8")
    assert (
        main(
            [
                "--import-root",
                str(source.parent),
                "--source-root",
                str(tmp_path / "store"),
                "--name",
                "sample",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert "manifest_digest" in output.out
    assert '"file_count": 1' in output.out
    assert '"status": "snapshot_created"' in output.out
    assert "PRIVATE_TEST_CONTENT" not in output.out
    assert not output.err


def test_operator_import_rejects_escape_with_safe_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "--import-root",
                str(tmp_path),
                "--source-root",
                str(tmp_path / "store"),
                "--name",
                "../secret-test-path",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert not output.out
    assert "SOURCE_" in output.err
    assert "secret-test-path" not in output.err
