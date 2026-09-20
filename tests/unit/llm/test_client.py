from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from privacy_guardian.config import LLMSettings
from privacy_guardian.llm.client import (
    BASE_URL,
    LLMClient,
    Probe,
    available_models,
    build_client,
    check_connection,
)
from privacy_guardian.llm.schemas import (
    DeepCheckNarrative,
    PolishedExplanation,
    RefinedClause,
    RefinedPolicy,
    RefinedPurpose,
)


def fallback() -> PolishedExplanation:
    return PolishedExplanation(explanation="Local fallback", rationale=["Offline result"])


def response(
    parsed: Any = None,
    *,
    finish: genai_types.FinishReason = genai_types.FinishReason.STOP,
    block: str | None = None,
    text: str | None = None,
) -> SimpleNamespace:
    body = text if text is not None else (parsed.model_dump_json() if parsed else "")
    return SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason=finish)],
        prompt_feedback=SimpleNamespace(block_reason=block),
        usage_metadata=SimpleNamespace(
            total_token_count=17, prompt_token_count=11, candidates_token_count=6
        ),
        parsed=parsed,
        text=body,
    )


class FakeModels:
    def __init__(self, result: object, listing: list[Any] | None = None) -> None:
        self.result = result
        self.listing = listing or []
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def generate_content_stream(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        body = str(getattr(self.result, "text", ""))
        # Fragments, the way the API actually delivers them: no single chunk is the object.
        for start in range(0, len(body), 9):
            yield response(None, text=body[start : start + 9])

    def list(self) -> list[Any]:
        return self.listing


class FakeClient:
    def __init__(self, result: object, listing: list[Any] | None = None) -> None:
        self.models = FakeModels(result, listing)


def enabled_settings() -> LLMSettings:
    return LLMSettings(enabled=True, model="gemini-test-model")


def transport(code: int) -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"error": {"message": "synthetic", "status": "ERROR"}})


def test_disabled_client_returns_fallback_without_touching_provider() -> None:
    provider = FakeClient(AssertionError("provider must not be called"))
    result = LLMClient(LLMSettings(enabled=False), client=provider).complete(
        "explanation_polishing", {"category": "email"}, PolishedExplanation, fallback()
    )
    assert result.value == fallback()
    assert result.assisted is False
    assert result.fallback_reason == "disabled"
    assert provider.models.calls == []


def test_success_uses_structured_output_and_sanitizes_input() -> None:
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
    call = provider.models.calls[0]
    assert call["model"] == "gemini-test-model"
    assert call["config"].response_schema is PolishedExplanation
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].automatic_function_calling.disable is True
    assert "4111111111111111" not in str(call["contents"])


def test_a_streamed_answer_is_assembled_before_it_is_validated() -> None:
    """No single fragment is the object, so the schema is applied to the whole of it."""
    parsed = PolishedExplanation(explanation="A long public policy was read.", rationale=["Terms"])
    provider = FakeClient(response(parsed))
    progress: list[str] = []
    result = LLMClient(enabled_settings(), client=provider).complete(
        "policy_refinement",
        {"public_document": "synthetic"},
        PolishedExplanation,
        fallback(),
        stream=True,
        on_progress=progress.append,
    )
    assert result.assisted is True
    assert result.value == parsed
    assert progress and set(progress) == {"Receiving privacy analysis"}


@pytest.mark.parametrize(
    ("provider_result", "reason"),
    [
        (response(None), "unparsed"),
        (response(fallback(), finish=genai_types.FinishReason.MAX_TOKENS), "incomplete"),
        (response(fallback(), finish=genai_types.FinishReason.SAFETY), "refusal"),
        (response(fallback(), block="PROHIBITED_CONTENT"), "refusal"),
        (ValueError("invalid typed response"), "invalid_output"),
        (httpx.ConnectError("unreachable"), "connection"),
        (httpx.ConnectTimeout("too slow"), "timeout"),
        (transport(429), "rate_limit"),
        (transport(400), "api_status"),
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


def test_a_missing_key_never_reaches_the_network() -> None:
    result = LLMClient(enabled_settings(), key_provider=lambda: None).complete(
        "explanation_polishing", {"category": "email"}, PolishedExplanation, fallback()
    )
    assert result.fallback_reason == "key_unavailable"
    assert result.assisted is False


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


@pytest.mark.parametrize(
    ("use", "schema", "value"),
    [
        (
            "policy_refinement",
            RefinedPolicy,
            RefinedPolicy(
                clauses=[
                    RefinedClause(
                        category="arbitration_or_class_waiver",
                        confidence=0.9,
                        citation="Synthetic clause",
                    )
                ],
                summary="One unusual clause.",
            ),
        ),
        (
            "purpose_refinement",
            RefinedPurpose,
            RefinedPurpose(purpose="ecommerce", confidence=0.9, rationale="Purpose evidence"),
        ),
        (
            "explanation_polishing",
            PolishedExplanation,
            PolishedExplanation(
                explanation="A contact category is requested.", rationale=["Account contact"]
            ),
        ),
        (
            "deep_check_narrative",
            DeepCheckNarrative,
            DeepCheckNarrative(
                summary="One finding.", findings=["Optional tracking"], clean_checks=["Uploads"]
            ),
        ),
    ],
)
def test_all_four_llm_uses_accept_typed_responses(use: str, schema: type[Any], value: Any) -> None:
    provider = FakeClient(response(value))
    result = LLMClient(enabled_settings(), client=provider).complete(
        use,
        {"categories": ["email"], "purpose": "account_creation"},
        schema,
        value,
    )
    assert result.assisted is True
    assert result.value == value
    assert provider.models.calls[0]["config"].response_schema is schema


def test_the_client_pins_the_endpoint_and_declines_the_sdk_retries() -> None:
    """An assessment that already fell back locally must not retry in the background.

    The SDK attempts five times by default and will take its base URL from the
    environment, which is a request going somewhere nobody in this app chose.
    """
    options = build_client("synthetic-key")._api_client._http_options
    assert options.base_url == BASE_URL
    assert options.retry_options.attempts == 1
    assert options.timeout == 20_000


def test_a_connection_test_reports_the_round_trip_and_what_the_key_can_call() -> None:
    provider = FakeClient(
        response(Probe(ok=True)),
        listing=[
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/text-embedding-004", supported_actions=["embedContent"]),
        ],
    )
    check = check_connection("gemini-2.5-flash", key="synthetic-key", client=provider)
    assert check.ok is True
    assert check.model == "gemini-2.5-flash"
    # Only models that can answer a prompt: an embedding model is not a choice here.
    assert check.models == ["gemini-2.5-flash"]


@pytest.mark.parametrize(
    ("model", "key", "result", "reason"),
    [
        ("gemini-2.5-flash", None, response(Probe(ok=True)), "key_unavailable"),
        ("", "synthetic-key", response(Probe(ok=True)), "model_unavailable"),
        ("gemini-2.5-flash", "synthetic-key", transport(400), "api_status"),
        ("gemini-2.5-flash", "synthetic-key", transport(429), "rate_limit"),
        ("gemini-2.5-flash", "synthetic-key", httpx.ConnectError("down"), "connection"),
        ("gemini-2.5-flash", "synthetic-key", response(None), "unparsed"),
    ],
)
def test_a_connection_test_says_which_setting_is_wrong(
    model: str, key: str | None, result: object, reason: str
) -> None:
    check = check_connection(model, key=key, client=FakeClient(result))
    assert check.ok is False
    assert check.reason == reason


def test_listing_models_survives_a_provider_that_will_not_answer() -> None:
    assert available_models("synthetic-key", client=FakeClient(transport(400))) == []


def test_opening_preferences_does_not_load_a_network_client() -> None:
    """Cloud assistance is off by default, so its SDK must not be on the startup path.

    Importing the provider SDK costs roughly a third of a second, and the model picker
    needs nothing from it but a list of strings and a result type.
    """
    dashboard = Path(__file__).resolve().parents[3] / "src/privacy_guardian/ui/dashboard.py"
    source = dashboard.read_text(encoding="utf-8").splitlines()
    imports = [line for line in source if line.startswith(("import ", "from "))]
    assert not [line for line in imports if "llm.client" in line]
    assert any("llm.catalog" in line for line in imports)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import privacy_guardian.ui.dashboard, sys; print('google.genai' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
