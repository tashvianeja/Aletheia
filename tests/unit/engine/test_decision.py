from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from privacy_guardian.core.events import (
    EVENT_ADAPTER,
    DataCategory,
    FormSubmitEvent,
    Outcome,
    Requester,
)
from privacy_guardian.engine.context import Observation, SiteOrAppProfile
from privacy_guardian.engine.decision import decide
from privacy_guardian.engine.necessity import Necessity, necessity_for, purposes
from privacy_guardian.engine.preferences import LearnedRules, Preference, UserPreferences, learn
from tests.fixtures.generate.generate_scenarios import generate as generate_scenarios

LEVEL = {Outcome.IGNORE: 0, Outcome.INFORM: 1, Outcome.INTERVENE: 2}


def _ask_preferences(category: DataCategory) -> UserPreferences:
    return UserPreferences(categories={category.value: Preference.ASK})


def test_golden_scenarios_match_risk_outcomes_explanations_and_actions(tmp_path: Path) -> None:
    for path in generate_scenarios(tmp_path):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        event = EVENT_ADAPTER.validate_python(scenario["event"])
        category = event.data_categories[0]
        decision = decide(event, preferences=_ask_preferences(category))
        assert decision.outcome.value == scenario["expected"]["outcome"], scenario["id"]
        assert decision.risk == pytest.approx(scenario["context"]["expected_risk"]), scenario["id"]
        rationale = (decision.explanation + " " + " ".join(decision.rationale)).lower()
        for keyword in scenario["expected"]["rationale_keywords"]:
            assert keyword.lower() in rationale, (scenario["id"], keyword, rationale)
        if decision.outcome == Outcome.INTERVENE:
            assert any(action != "continue" for action in decision.actions)
            assert decision.default_action in decision.actions
            assert decision.default_action != "continue"


def test_unknown_purpose_is_reasonable_low_confidence_and_explains_uncertainty() -> None:
    assessment = necessity_for("unknown", DataCategory.CREDENTIALS_PASSWORD, 0.0)
    assert assessment.verdict == Necessity.REASONABLE
    assert assessment.confidence <= 0.2
    assert "uncertain" in assessment.rationale.lower()
    event = FormSubmitEvent(
        requester=Requester(display_name="Unclassified test site"),
        data_categories=[DataCategory.CREDENTIALS_PASSWORD],
    )
    decision = decide(event, preferences=_ask_preferences(DataCategory.CREDENTIALS_PASSWORD))
    assert decision.outcome == Outcome.INFORM
    assert "uncertain" in decision.explanation.lower()


@settings(max_examples=80, deadline=None)
@given(
    purpose=st.sampled_from(purposes()),
    category=st.sampled_from(tuple(DataCategory)),
)
def test_raising_category_to_always_warn_never_lowers_outcome(
    purpose: str, category: DataCategory
) -> None:
    event = FormSubmitEvent(
        requester=Requester(purpose=purpose, purpose_confidence=1.0),
        data_categories=[category],
    )
    baseline = decide(
        event, preferences=UserPreferences(categories={category.value: Preference.ASK})
    )
    warned = decide(
        event, preferences=UserPreferences(categories={category.value: Preference.ALWAYS_WARN})
    )
    assert LEVEL[warned.outcome] >= LEVEL[baseline.outcome]


def test_learning_downgrades_only_unprotected_intervention_to_inform() -> None:
    phone_event = FormSubmitEvent(
        requester=Requester(purpose="saas_b2b", purpose_confidence=1.0),
        data_categories=[DataCategory.PHONE],
    )
    consequential_profile = SiteOrAppProfile(retention="after_deletion")
    rules = LearnedRules()
    for _ in range(3):
        rules = learn(rules, [DataCategory.PHONE], "saas_b2b", "continue")
    before = decide(
        phone_event,
        profile=consequential_profile,
        preferences=_ask_preferences(DataCategory.PHONE),
    )
    after = decide(
        phone_event,
        profile=consequential_profile,
        preferences=_ask_preferences(DataCategory.PHONE),
        learned_rules=rules,
    )
    assert before.outcome == Outcome.INTERVENE
    assert after.outcome == Outcome.INFORM

    passport_event = phone_event.model_copy(
        update={"data_categories": [DataCategory.GOVERNMENT_ID_PASSPORT]}
    )
    protected_rules = LearnedRules()
    for _ in range(3):
        protected_rules = learn(
            protected_rules, [DataCategory.GOVERNMENT_ID_PASSPORT], "saas_b2b", "continue"
        )
    protected_decision = decide(
        passport_event,
        profile=consequential_profile,
        preferences=_ask_preferences(DataCategory.GOVERNMENT_ID_PASSPORT),
        learned_rules=protected_rules,
    )
    assert protected_decision.outcome == Outcome.INTERVENE


def test_learning_and_rate_limit_can_never_silence_high_risk_request() -> None:
    event = FormSubmitEvent(
        requester=Requester(purpose="recipe", purpose_confidence=1.0),
        data_categories=[DataCategory.ACCESSIBILITY],
    )
    rules = LearnedRules()
    for _ in range(3):
        rules = learn(rules, [DataCategory.ACCESSIBILITY], "recipe", "continue")
    profile = SiteOrAppProfile(
        recent_observations=[
            Observation(categories=[DataCategory.ACCESSIBILITY], ts=datetime.now(UTC))
        ]
    )
    decision = decide(
        event,
        profile=profile,
        preferences=_ask_preferences(DataCategory.ACCESSIBILITY),
        learned_rules=rules,
    )
    assert decision.risk >= 0.55
    assert decision.outcome == Outcome.INFORM
