"""Security scan summaries preserve a clear release gate without leaking findings."""

from __future__ import annotations

import pytest

from scripts.security_report import ScanSummary, summarize


def test_fixable_high_severity_and_secrets_fail_the_gate() -> None:
    report: object = {
        "SchemaVersion": 2,
        "Results": [
            {
                "Vulnerabilities": [
                    {"Severity": "HIGH", "FixedVersion": "2.0"},
                    {"Severity": "CRITICAL", "FixedVersion": ""},
                    {"Severity": "MEDIUM", "FixedVersion": "3.0"},
                ],
                "Secrets": [{"RuleID": "generic-api-key", "Match": "must-not-print"}],
            }
        ],
    }

    summary = summarize(report)

    assert summary == ScanSummary(secrets=1, high_or_critical=2, fixable_high_or_critical=1)
    assert not summary.passes_gate
    assert "must-not-print" not in str(summary)


def test_unfixed_findings_are_reported_but_do_not_fail_fixable_gate() -> None:
    report: object = {
        "SchemaVersion": 2,
        "Results": [{"Vulnerabilities": [{"Severity": "HIGH", "FixedVersion": ""}]}],
    }

    summary = summarize(report)

    assert summary.high_or_critical == 1
    assert summary.fixable_high_or_critical == 0
    assert summary.passes_gate


@pytest.mark.parametrize("report", [{}, {"SchemaVersion": 2, "Results": "invalid"}])
def test_invalid_scanner_output_fails_closed(report: object) -> None:
    with pytest.raises(ValueError):
        summarize(report)
