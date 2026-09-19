from __future__ import annotations

import os

import pytest

from privacy_guardian.config import LLMSettings
from privacy_guardian.llm.client import LLMClient
from privacy_guardian.llm.schemas import PolishedExplanation


@pytest.mark.llm
def test_opt_in_real_responses_api_uses_only_synthetic_category_context() -> None:
    if os.getenv("PRIVACY_GUARDIAN_RUN_LLM_TEST") != "1":
        pytest.skip("set PRIVACY_GUARDIAN_RUN_LLM_TEST=1 to opt into the provider call")
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY is absent")
    fallback = PolishedExplanation(
        explanation="A site requests an email address.", rationale=["Account contact"]
    )
    result = LLMClient(LLMSettings(enabled=True), key_provider=lambda: key).complete(
        "explanation_polishing",
        {
            "categories": ["email"],
            "purpose": "account_creation",
            "necessity": "reasonable",
        },
        PolishedExplanation,
        fallback,
    )
    assert isinstance(result.value, PolishedExplanation)
    assert result.value.explanation
    assert result.assisted is True
    assert result.fallback_reason is None
