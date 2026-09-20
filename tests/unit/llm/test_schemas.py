from __future__ import annotations

import pytest
from pydantic import ValidationError

from aletheia.llm.schemas import RefinedClause, RefinedPolicy, RefinedPurpose


def test_refined_purpose_is_constrained_to_local_taxonomy() -> None:
    assert (
        RefinedPurpose(purpose="recipe", confidence=0.8, rationale="Recipe signals").purpose
        == "recipe"
    )
    with pytest.raises(ValidationError):
        RefinedPurpose(purpose="invented_category", confidence=0.8, rationale="Unsupported")


def test_refined_clause_is_constrained_to_local_taxonomy() -> None:
    clause = RefinedClause(
        category="retention_after_deletion",
        confidence=0.9,
        citation="Backups may remain after account deletion.",
    )
    assert clause.category == "retention_after_deletion"
    with pytest.raises(ValidationError):
        RefinedClause(category="secret_new_clause", confidence=0.9, citation="Synthetic")


def test_refined_policy_forbids_unexpected_model_fields() -> None:
    with pytest.raises(ValidationError):
        RefinedPolicy(clauses=[], summary="No material clauses", action="ignore")  # type: ignore[call-arg]
