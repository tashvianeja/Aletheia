from __future__ import annotations

import os

import pytest

from privacy_guardian.config import LLMSettings
from privacy_guardian.llm.client import LLMClient
from privacy_guardian.llm.schemas import PolishedExplanation


def _live_key() -> str:
    if os.getenv("PRIVACY_GUARDIAN_RUN_LLM_TEST") != "1":
        pytest.skip("set PRIVACY_GUARDIAN_RUN_LLM_TEST=1 to opt into the provider call")
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY is absent")
    return key


@pytest.mark.llm
def test_opt_in_real_gemini_call_uses_only_synthetic_category_context() -> None:
    key = _live_key()
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


@pytest.mark.llm
def test_opt_in_connection_check_reaches_the_real_api() -> None:
    """What the Preferences "Test" button does, against the provider rather than a fake."""
    from privacy_guardian.llm.client import check_connection

    key = _live_key()
    check = check_connection(LLMSettings().model, key=key)
    assert check.ok is True, check.reason
    assert check.latency_ms > 0
    assert check.models, "a working key should be able to list the models it can call"
