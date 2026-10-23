"""Distinguish opaque Docker layer bytes from files inside those layers."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.publication_asset_audit import extract_and_classify


def _archive(path: Path, config: bytes = b'{"config": "public"}\n') -> tuple[str, str]:
    layer_digest = "a" * 64
    config_digest = "b" * 64
    layer_bytes = io.BytesIO()
    with tarfile.open(fileobj=layer_bytes, mode="w") as layer:
        content = b"public fixture\n"
        member = tarfile.TarInfo("app/notice.txt")
        member.size = len(content)
        layer.addfile(member, io.BytesIO(content))
    with tarfile.open(path, mode="w:gz") as outer:
        for digest, content in (
            (layer_digest, layer_bytes.getvalue()),
            (config_digest, config),
        ):
            member = tarfile.TarInfo(f"blobs/sha256/{digest}")
            member.size = len(content)
            outer.addfile(member, io.BytesIO(content))
    return layer_digest, config_digest


def _report(path: Path, matched_file: str) -> None:
    path.write_text(
        json.dumps([{"RuleID": "generic-api-key", "File": matched_file}]), encoding="utf-8"
    )


def test_extracts_layer_and_classifies_opaque_blob_match(tmp_path: Path) -> None:
    archive = tmp_path / "images.tar.gz"
    digest, _ = _archive(archive)
    report = tmp_path / "report.json"
    _report(report, f"{archive}/blobs/sha256/{digest}")

    summary = extract_and_classify(archive, report, tmp_path / "layers")

    assert summary.layer_count == 1
    assert summary.opaque_findings == 1
    extracted = list((tmp_path / "layers").glob("*.tar"))
    assert len(extracted) == 1
    with tarfile.open(extracted[0]) as layer:
        notice = layer.extractfile("app/notice.txt")
        assert notice is not None
        assert notice.read() == b"public fixture\n"


def test_layers_are_extracted_without_raw_findings(tmp_path: Path) -> None:
    archive = tmp_path / "images.tar.gz"
    _archive(archive)
    report = tmp_path / "report.json"
    report.write_text("[]", encoding="utf-8")

    summary = extract_and_classify(archive, report, tmp_path / "layers")

    assert summary.layer_count == 1
    assert summary.opaque_findings == 0


@pytest.mark.parametrize("kind", ["text_asset", "non_archive_blob"])
def test_other_raw_matches_remain_blocking(tmp_path: Path, kind: str) -> None:
    archive = tmp_path / "images.tar.gz"
    _, config_digest = _archive(archive)
    report = tmp_path / "report.json"
    matched_file = (
        "release-metadata.json"
        if kind == "text_asset"
        else f"{archive}/blobs/sha256/{config_digest}"
    )
    _report(report, matched_file)

    with pytest.raises(ValueError, match="Unclassified release finding"):
        extract_and_classify(archive, report, tmp_path / "layers")


def test_failure_reports_only_the_redacted_key_name(tmp_path: Path) -> None:
    archive = tmp_path / "images.tar.gz"
    _, config_digest = _archive(archive)
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            [
                {
                    "RuleID": "generic-api-key",
                    "File": f"{archive}/blobs/sha256/{config_digest}",
                    "Secret": "REDACTED",
                    "Match": 'GPG_KEY=REDACTED"',
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unclassified release finding") as error:
        extract_and_classify(archive, report, tmp_path / "layers")
    assert "match_keys=GPG_KEY" in str(error.value)
    assert "REDACTED" not in str(error.value)


@pytest.mark.parametrize(
    "fingerprint,accepted",
    [
        ("7169605F62C751356D054A26A821E680E5FA6305", True),
        ("0000000000000000000000000000000000000000", False),
    ],
)
def test_only_known_public_signing_fingerprint_is_exempt(
    tmp_path: Path, fingerprint: str, accepted: bool
) -> None:
    archive = tmp_path / "images.tar.gz"
    _, digest = _archive(
        archive,
        json.dumps({"config": {"Env": [f"GPG_KEY={fingerprint}"]}}).encode("utf-8"),
    )
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            [
                {
                    "RuleID": "generic-api-key",
                    "File": f"{archive}/blobs/sha256/{digest}",
                    "Secret": "REDACTED",
                    "Match": 'GPG_KEY=REDACTED"',
                }
            ]
        ),
        encoding="utf-8",
    )

    if accepted:
        summary = extract_and_classify(archive, report, tmp_path / "layers")
        assert summary.public_signing_key_findings == 1
    else:
        with pytest.raises(ValueError, match="Unclassified release finding"):
            extract_and_classify(archive, report, tmp_path / "layers")
