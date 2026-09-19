from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from privacy_guardian.analysis.policy import (
    PolicyProfile,
    TermsProfile,
    analyze_policy,
    analyze_terms,
)

CORPUS_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "corpora"


def _micro_f1(
    paths: list[Path],
    analyze: Callable[[str], Any],
    expected_key: str,
    actual: Callable[[Any], set[str]],
) -> float:
    true_positive = false_positive = false_negative = 0
    for path in paths:
        expected = set(json.loads(path.with_suffix(".json").read_text())[expected_key])
        observed = actual(analyze(path.read_text(encoding="utf-8")))
        true_positive += len(expected & observed)
        false_positive += len(observed - expected)
        false_negative += len(expected - observed)
    return 2 * true_positive / (2 * true_positive + false_positive + false_negative)


def test_terms_corpus_offline_f1_at_least_point_85() -> None:
    paths = sorted((CORPUS_ROOT / "terms").glob("*.txt"))
    assert len(paths) >= 15
    f1 = _micro_f1(
        paths, analyze_terms, "clauses", lambda profile: {c.category for c in profile.clauses}
    )
    assert f1 >= 0.85, f"terms F1={f1:.3f}"


@pytest.mark.parametrize(
    ("key", "extract"),
    [
        ("purposes", lambda profile: set(profile.purposes)),
        ("shares_with", lambda profile: set(profile.shares_with)),
    ],
)
def test_policy_corpus_offline_f1_at_least_point_85(key: str, extract) -> None:
    paths = sorted((CORPUS_ROOT / "policies").glob("*.txt"))
    assert len(paths) >= 15
    f1 = _micro_f1(paths, analyze_policy, key, extract)
    assert f1 >= 0.85, f"policy {key} F1={f1:.3f}"


def test_missing_policy_is_explicit_finding() -> None:
    profile = analyze_policy("")
    assert isinstance(profile, PolicyProfile)
    assert profile.missing is True
    assert any("no privacy policy" in warning.lower() for warning in profile.warnings)


def test_terms_negations_are_not_reported() -> None:
    profile = analyze_terms(
        "We do not sell personal information. Subscriptions do not renew automatically. "
        "We never use submitted content to train machine learning models."
    )
    assert isinstance(profile, TermsProfile)
    assert profile.clauses == []


def test_policy_necessity_changes_with_site_purpose() -> None:
    text = "We collect precise location information to provide the service."
    recipe = analyze_policy(text, purpose="recipe")
    navigation = analyze_policy(text, purpose="maps_navigation")
    assert recipe.necessity_statements != navigation.necessity_statements
    assert "does not appear necessary" in " ".join(recipe.necessity_statements).lower()
    assert "is needed" in " ".join(navigation.necessity_statements).lower()
