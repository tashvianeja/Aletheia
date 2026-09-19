from __future__ import annotations

import pytest

from tests.check_coverage import CORE_PREFIXES, line_counts, percentage


def test_coverage_gate_aggregates_required_modules_independently_from_overall() -> None:
    report = {
        "src/privacy_guardian/core/service.py": {
            "summary": {"num_statements": 80, "covered_lines": 68}
        },
        "src/privacy_guardian/engine/decision.py": {
            "summary": {"num_statements": 20, "covered_lines": 17}
        },
        "src/privacy_guardian/ui/dashboard.py": {
            "summary": {"num_statements": 100, "covered_lines": 40}
        },
    }
    assert line_counts(report, CORE_PREFIXES) == (85, 100)
    assert percentage(line_counts(report, CORE_PREFIXES)) == 85.0
    assert percentage(line_counts(report)) == 62.5


def test_coverage_gate_normalizes_windows_report_paths() -> None:
    report = {
        r"src\privacy_guardian\storage\store.py": {
            "summary": {"num_statements": 10, "covered_lines": 9}
        }
    }
    assert line_counts(report, CORE_PREFIXES) == (9, 10)


def test_coverage_gate_refuses_empty_or_mismatched_reports() -> None:
    with pytest.raises(ValueError, match="matching statements"):
        percentage(line_counts({}, CORE_PREFIXES))
    unrelated = {"third_party/module.py": {"summary": {"num_statements": 10, "covered_lines": 10}}}
    with pytest.raises(ValueError, match="matching statements"):
        percentage(line_counts(unrelated, CORE_PREFIXES))
