from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from privacy_guardian.core.events import (
    EVENT_ADAPTER,
    Decision,
    FormField,
    FormSubmitEvent,
    Outcome,
    Requester,
)
from tests.fixtures.generate.generate_scenarios import generate as generate_scenarios


def test_all_generated_golden_events_match_executable_contract(tmp_path: Path) -> None:
    for path in generate_scenarios(tmp_path):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        event = EVENT_ADAPTER.validate_python(scenario["event"])
        assert event.requester.purpose == scenario["context"]["purpose"]


def test_event_models_reject_raw_form_values() -> None:
    with pytest.raises(ValidationError):
        FormField(field_id="phone", label="Phone", value="+1 202 555 0100")  # type: ignore[call-arg]


def test_event_models_reject_unknown_raw_content_field() -> None:
    with pytest.raises(ValidationError):
        FormSubmitEvent(
            requester=Requester(origin="https://example.test"),
            raw_content="4111111111111111",  # type: ignore[call-arg]
        )


def test_requester_key_uses_nonempty_stable_identity_precedence() -> None:
    assert (
        Requester(origin="https://example.test", bundle_id="com.example.app").key
        == "https://example.test"
    )
    assert Requester(kind="application", bundle_id="com.example.app").key == "com.example.app"
    assert Requester(kind="application", exe_path=r"C:\Synthetic\app.exe").key.endswith("app.exe")


def test_intervention_contract_has_a_safe_non_continue_action() -> None:
    decision = Decision(
        event_id="synthetic-event",
        outcome=Outcome.INTERVENE,
        risk=0.9,
        explanation="A test site requests a synthetic passport for an unrelated purpose.",
        actions=["cancel", "continue"],
        default_action="cancel",
    )
    assert any(action != "continue" for action in decision.actions)
    assert decision.default_action in decision.actions
    assert decision.default_action != "continue"
