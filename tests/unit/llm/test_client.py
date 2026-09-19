from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from privacy_guardian.config import LLMSettings
from privacy_guardian.llm.client import LLMClient
from privacy_guardian.llm.schemas import PolishedExplanation


def fallback() -> PolishedExplanation:
    return PolishedExplanation(explanation="Local fallback", rationale=["Offline result"])


def response(
    parsed: PolishedExplanation | None = None,
    *,
    status: str = "completed",
    incomplete: object | None = None,
    refusal: bool = False,
) -> SimpleNamespace:
    content = [SimpleNamespace(type="refusal" if refusal else "output_text")]
    return SimpleNamespace(
        status=status,
        incomplete_details=incomplete,
        output=[SimpleNamespace(type="message", content=content)],
        usage=SimpleNamespace(total_tokens=17),
        output_parsed=parsed,
    )


class FakeResponses:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class FakeClient:
    def __init__(self, result: object) -> None:
        self.responses = FakeResponses(result)


def enabled_settings() -> LLMSettings:
    return LLMSettings(enabled=True, model="test-reasoning-model")


def test_disabled_client_returns_fallback_without_touching_provider() -> None:
    provider = FakeClient(AssertionError("provider must not be called"))
    result = LLMClient(LLMSettings(enabled=False), client=provider).complete(
        "explanation_polishing", {"category": "email"}, PolishedExplanation, fallback()
    )
    assert result.value == fallback()
    assert result.assisted is False
    assert result.fallback_reason == "disabled"
    assert provider.responses.calls == []


def test_success_uses_typed_responses_and_sanitizes_input() -> None:
    parsed = PolishedExplanation(
        explanation="This site requests a card number.", rationale=["Payment"]
    )
    provider = FakeClient(response(parsed))
    result = LLMClient(enabled_settings(), client=provider).complete(
        "explanation_polishing",
        {"raw": "4111111111111111", "category": "financial.card_number"},
        PolishedExplanation,
        fallback(),
    )
    assert result.assisted is True
    assert result.value == parsed
    call = provider.responses.calls[0]
    assert call["model"] == "test-reasoning-model"
    assert call["text_format"] is PolishedExplanation
    assert call["store"] is False
    assert call["prompt_cache_key"].endswith("explanation_polishing")
    assert "4111111111111111" not in repr(call["input"])


@pytest.mark.parametrize(
    ("provider_result", "reason"),
    [
        (response(None), "unparsed"),
        (response(fallback(), status="incomplete", incomplete=object()), "incomplete"),
        (response(fallback(), refusal=True), "refusal"),
        (ValueError("invalid typed response"), "invalid_output"),
        (
            APIConnectionError(
                request=httpx.Request("POST", "https://api.openai.com/v1/responses")
            ),
            "connection",
        ),
        (
            APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses")),
            "timeout",
        ),
    ],
)
def test_provider_failures_return_local_fallback(provider_result: object, reason: str) -> None:
    provider = FakeClient(provider_result)
    result = LLMClient(enabled_settings(), client=provider).complete(
        "explanation_polishing", {"category": "email"}, PolishedExplanation, fallback()
    )
    assert result.value == fallback()
    assert result.assisted is False
    assert result.fallback_reason == reason


def test_invalid_or_sensitive_model_output_falls_back() -> None:
    parsed = PolishedExplanation(
        explanation="Call morgan.testperson@example.test with card 4111111111111111",
        rationale=["Leaked identifier"],
    )
    provider = FakeClient(response(parsed))
    result = LLMClient(enabled_settings(), client=provider).complete(
        "explanation_polishing", {"category": "financial"}, PolishedExplanation, fallback()
    )
    assert result.assisted is True
    assert "4111111111111111" not in result.value.explanation
    assert "morgan.testperson" not in result.value.explanation
