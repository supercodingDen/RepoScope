"""Summarize Trivy JSON without printing secret matches or raw findings."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """Counts needed for the current source and fixable-vulnerability gate."""

    secrets: int
    high_or_critical: int
    fixable_high_or_critical: int

    @property
    def passes_gate(self) -> bool:
        return self.secrets == 0 and self.fixable_high_or_critical == 0


def _finding_list(result: dict[str, object], name: str) -> list[object]:
    """Read one optional Trivy result list, rejecting malformed reports."""
    value = result.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Invalid scanner report")
    return value


def summarize(report: object) -> ScanSummary:
    """Count findings without retaining or exposing matched secret text."""
    if not isinstance(report, dict) or not isinstance(report.get("SchemaVersion"), int):
        raise ValueError("Invalid scanner report")
    results = report.get("Results")
    if not isinstance(results, list):
        raise ValueError("Invalid scanner report")
    secrets = 0
    high_or_critical = 0
    fixable_high_or_critical = 0
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Invalid scanner report")
        secret_findings = _finding_list(result, "Secrets")
        if any(not isinstance(finding, dict) for finding in secret_findings):
            raise ValueError("Invalid scanner report")
        secrets += len(secret_findings)
        for finding in _finding_list(result, "Vulnerabilities"):
            if not isinstance(finding, dict):
                raise ValueError("Invalid scanner report")
            severity = finding.get("Severity")
            fixed_version = finding.get("FixedVersion")
            if (
                not isinstance(severity, str)
                or fixed_version is not None
                and not isinstance(fixed_version, str)
            ):
                raise ValueError("Invalid scanner report")
            if severity in {"HIGH", "CRITICAL"}:
                high_or_critical += 1
                if fixed_version:
                    fixable_high_or_critical += 1
    return ScanSummary(secrets, high_or_critical, fixable_high_or_critical)


def main(arguments: Sequence[str] | None = None) -> int:
    """Fail closed for source and image scans with a compact count-only result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--label", required=True)
    args = parser.parse_args(arguments)
    try:
        with args.report.open(encoding="utf-8") as stream:
            report: object = json.load(stream)
        summary = summarize(report)
    except (OSError, ValueError, json.JSONDecodeError):
        print(f"{args.label}: scanner report missing or invalid")
        return 1
    print(
        f"{args.label}: secrets={summary.secrets}, "
        f"high/critical={summary.high_or_critical}, "
        f"fixable high/critical={summary.fixable_high_or_critical}"
    )
    return 0 if summary.passes_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
