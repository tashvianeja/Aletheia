from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aletheia.core.events import (
    EVENT_ADAPTER,
    DataCategory,
    FormSubmitEvent,
    Outcome,
    Requester,
)
from aletheia.engine.context import Observation, SiteOrAppProfile
from aletheia.engine.decision import decide
from aletheia.engine.necessity import Necessity, necessity_for, purposes
from aletheia.engine.preferences import LearnedRules, Preference, UserPreferences, learn
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


def _standing_grant(existing: bool = True, purpose: str = "unknown") -> Outcome:
    from aletheia.core.events import PermissionRequestEvent

    return decide(
        PermissionRequestEvent(
            source="os",
            requester=Requester(
                kind="application",
                bundle_id="com.synthetic.helper",
                display_name="helper",
                purpose=purpose,
                purpose_confidence=0.9 if purpose != "unknown" else 0.0,
            ),
            data_categories=[DataCategory.ACCESSIBILITY],
            permission="accessibility",
            state="granted",
            existing=existing,
        )
    ).outcome


def test_a_permission_already_held_is_not_raised_as_something_to_review() -> None:
    """The bug this guards: every settled grant on the machine announced as a request."""
    assert _standing_grant(existing=True) == Outcome.IGNORE
    assert _standing_grant(existing=False) != Outcome.IGNORE


def test_a_permission_already_held_is_still_raised_when_it_is_unnecessary() -> None:
    """Quiet about the ordinary is not the same as quiet about the unearned."""
    assert necessity_for("recipe", DataCategory.ACCESSIBILITY, 1.0).verdict in {
        Necessity.UNNECESSARY,
        Necessity.RED_FLAG,
    }
    assert _standing_grant(existing=True, purpose="recipe") != Outcome.IGNORE


def test_closing_a_desktop_notice_is_an_option_the_decision_offers() -> None:
    from aletheia.core.events import PermissionRequestEvent

    decision = decide(
        PermissionRequestEvent(
            source="os",
            requester=Requester(kind="application", bundle_id="com.synthetic.helper"),
            data_categories=[DataCategory.CAMERA],
            permission="camera",
        )
    )

    assert "continue" in decision.actions
    assert decision.default_action == "open_settings"


@pytest.mark.parametrize(
    ("state", "existing", "expected"),
    [
        ("requested", False, "Snipper is asking for your camera."),
        ("granted", False, "Snipper was given access to your camera."),
        ("granted", True, "Snipper already has access to your camera."),
        ("active", False, "Snipper is using your camera."),
    ],
)
def test_a_permission_is_described_as_what_actually_happened(
    state: str, existing: bool, expected: str
) -> None:
    from aletheia.core.events import PermissionRequestEvent
    from aletheia.engine.context import analyze_context
    from aletheia.engine.explain import explain

    event = PermissionRequestEvent(
        source="os",
        requester=Requester(kind="application", bundle_id="com.synthetic", display_name="Snipper"),
        data_categories=[DataCategory.CAMERA],
        permission="camera",
        state=state,  # type: ignore[arg-type]
        existing=existing,
    )
    headline, _body, _rows, _why = explain(
        event, analyze_context(event.requester, event.data_categories), SiteOrAppProfile()
    )

    assert headline == expected


def test_broad_access_already_held_is_described_as_held() -> None:
    from aletheia.core.events import SystemAccessEvent
    from aletheia.engine.context import analyze_context
    from aletheia.engine.explain import explain

    event = SystemAccessEvent(
        source="os",
        requester=Requester(kind="application", bundle_id="com.synthetic", display_name="Snipper"),
        data_categories=[DataCategory.FILES_BROAD, DataCategory.ACCESSIBILITY],
        accesses=["files_broad", "accessibility"],
        breadth=0.7,
        existing=True,
    )
    headline, _body, _rows, _why = explain(
        event, analyze_context(event.requester, event.data_categories), SiteOrAppProfile()
    )

    assert headline == "Snipper already has broad access to your computer."


def test_upload_rows_say_where_each_thing_was_found() -> None:
    from aletheia.core.events import FileUploadEvent, Finding

    event = FileUploadEvent(
        requester=Requester(
            kind="website",
            origin="https://shrinkpix.test",
            display_name="shrinkpix.test",
            purpose="image_tool",
            purpose_confidence=0.9,
        ),
        filename="statement.pdf",
    )
    decision = decide(
        event,
        [
            Finding(category=DataCategory.FINANCIAL_IBAN, page=2),
            Finding(category=DataCategory.FINANCIAL_IBAN, page=5),
            Finding(category=DataCategory.LOCATION_PRECISE, span_ref="metadata"),
        ],
    )
    rows = {row.label: row.detail for row in decision.findings}

    assert rows["Bank account (IBAN)"] == "Pages 2, 5"
    assert rows["Precise location"] == "Recorded in the file's own metadata"


def test_a_single_page_document_is_not_labelled_page_one() -> None:
    from aletheia.core.events import Finding
    from aletheia.engine.explain import evidence

    assert evidence([Finding(category=DataCategory.EMAIL, page=1)]) == {}


def test_tracking_rows_group_the_mechanisms_into_what_they_do() -> None:
    from aletheia.core.events import TrackingEvent
    from aletheia.engine.presentation import tracking_mechanisms, tracking_rows

    event = TrackingEvent(
        requester=Requester(kind="website", origin="https://news.test"),
        tracker_domains=["criteo.com", "doubleclick.net"],
        fingerprinting=True,
        signals=[
            "known_tracker_requests",
            "cross_origin_storage_identifier",
            "tracking_pixels",
            "url_decoration",
            "fingerprinting",
        ],
    )
    rows = tracking_rows(event)

    # Five mechanisms, two things they do to the person.
    assert [row.label for row in rows] == [
        "Shares what you do here with 2 other companies",
        "Recognises this device even after you clear cookies",
    ]
    assert rows[0].detail == "criteo.com, doubleclick.net"
    # The detector's own name for a mechanism is not an explanation of it, and the
    # explanations belong under "Why am I seeing this?", not on the card.
    assert tracking_mechanisms(event) == [
        "Reuses one stored identifier across separate websites.",
        "Loads invisible images that report which pages you open.",
        "Tags the links you follow with an identifier for you.",
    ]


def test_an_email_match_is_its_own_row_because_it_is_not_just_a_browser() -> None:
    from aletheia.core.events import TrackingEvent
    from aletheia.engine.presentation import tracking_rows

    event = TrackingEvent(
        requester=Requester(kind="website", origin="https://news.test"),
        tracker_domains=["criteo.com"],
        signals=["known_tracker_requests", "identity_linking"],
    )

    assert [row.label for row in tracking_rows(event)] == [
        "Shares what you do here with 1 other company",
        "Can match this browsing to your email address",
    ]


def test_page_context_warnings_name_the_site() -> None:
    from aletheia.sensors.browser_bridge import prepare_context

    prepared = prepare_context({"origin": "https://news.example", "signals": {}})

    assert prepared["requester"]["display_name"] == "news.example"


def test_a_cookie_banner_is_one_choice_so_it_reads_as_one_row() -> None:
    from aletheia.core.events import ConsentBannerEvent
    from aletheia.engine.explain import consent_findings, consent_meanings

    event = ConsentBannerEvent(
        requester=Requester(kind="website", origin="https://news.test"),
        cmp="onetrust",
        purposes=["necessary", "analytics", "advertising", "personalisation", "social"],
        vendor_count=812,
        dark_patterns=["hidden_reject"],
    )
    rows = consent_findings(event)

    assert [row.label for row in rows] == [
        "Wants cookies for analytics, advertising, personalisation and 1 more",
        "Shares what it learns with 812 other companies",
    ]
    # Nobody objects to the necessary ones, so they are not a row of their own.
    assert not any("necessary" in row.label.lower() for row in rows)
    assert len(consent_meanings(event)) == 4


def test_a_form_card_lists_what_needs_looking_at_not_what_is_fine() -> None:
    from aletheia.core.events import FormField, FormObservedEvent
    from aletheia.engine.explain import form_findings

    fields = [
        FormField(field_id="e", category=DataCategory.EMAIL),
        FormField(field_id="p", category=DataCategory.PHONE),
        FormField(field_id="d", category=DataCategory.DOB),
    ]
    event = FormObservedEvent(requester=Requester(kind="website"), fields=fields)

    flagged = form_findings(event, {DataCategory.PHONE, DataCategory.DOB})
    assert [row.label for row in flagged] == ["Phone number", "Date of birth"]

    # With nothing to flag, what is fine is the whole answer.
    clean = form_findings(event, set())
    assert all(row.severity == "ok" for row in clean) and len(clean) == 3


def test_the_card_does_not_say_in_prose_what_the_rows_already_say() -> None:
    from aletheia.core.events import ConsentBannerEvent, TrackingEvent

    site = Requester(kind="website", origin="https://news.test", display_name="news.test")
    tracking = decide(
        TrackingEvent(
            requester=site,
            tracker_domains=["criteo.com"],
            signals=["known_tracker_requests"],
            confidence=0.6,
        )
    )
    banner = decide(
        ConsentBannerEvent(requester=site, cmp="onetrust", purposes=["necessary", "advertising"])
    )

    assert tracking.headline == "news.test is building an advertising profile."
    assert tracking.body == ""
    assert banner.body == ""
    for decision in (tracking, banner):
        assert len(decision.findings) <= 3


def test_urgency_follows_the_verdict_and_the_risk() -> None:
    """The tier is the colour the widget wears: two reds for what holds something up,
    amber for a warning, green for fine or handled, blue for a plain note."""
    from aletheia.core.events import Decision, DecisionFinding, Outcome
    from aletheia.engine.presentation import urgency_for

    def made(outcome: Outcome, risk: float, **extra: object) -> Decision:
        return Decision(event_id="e", outcome=outcome, risk=risk, explanation="x", **extra)

    assert urgency_for(made(Outcome.INTERVENE, 1.0)) == "act_now"
    assert urgency_for(made(Outcome.INTERVENE, 0.75)) == "act_now"
    assert urgency_for(made(Outcome.INTERVENE, 0.55)) == "attention"
    assert urgency_for(made(Outcome.INFORM, 0.4)) == "heads_up"
    assert (
        urgency_for(made(Outcome.INFORM, 0.1, findings=[DecisionFinding(label="w")])) == "heads_up"
    ), "a warning row makes it a warning whatever the score"
    assert urgency_for(made(Outcome.INFORM, 0.1)) == "all_clear"
    assert urgency_for(made(Outcome.INFORM, 0.6, auto_action="reject_optional")) == "all_clear", (
        "done for the person is reported as handled, not as a warning"
    )
    assert urgency_for(made(Outcome.IGNORE, 0.3)) == "note"


def test_decisions_leave_the_engine_with_their_tier_set() -> None:
    from aletheia.core.events import DataCategory, FileUploadEvent, Requester

    upload = FileUploadEvent(
        filename="passport.pdf",
        requester=Requester(
            origin="https://shrinkpix.example",
            display_name="shrinkpix.example",
            purpose="image_tool",
            purpose_confidence=0.9,
        ),
        data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT, DataCategory.FULL_NAME],
    )
    verdict = decide(upload)
    assert verdict.outcome.value == "INTERVENE"
    assert verdict.urgency == "act_now"
