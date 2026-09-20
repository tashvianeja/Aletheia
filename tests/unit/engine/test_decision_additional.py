from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aletheia.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    FileUploadEvent,
    Outcome,
    PermissionRequestEvent,
    PolicyDocumentEvent,
    Requester,
    ScreenCaptureEvent,
    SystemAccessEvent,
    TrackingEvent,
)
from aletheia.engine.context import Observation, SiteOrAppProfile
from aletheia.engine.decision import DecisionEngine, decide
from aletheia.engine.preferences import Preference, UserPreferences


def requester(purpose: str = "recipe") -> Requester:
    return Requester(
        kind="website",
        origin="https://synthetic.example",
        display_name="Synthetic site",
        purpose=purpose,
        purpose_confidence=1,
    )


def test_tracking_distinguishes_no_signal_and_persistent_activity() -> None:
    quiet = decide(TrackingEvent(requester=requester(), confidence=1))
    tracked = decide(
        TrackingEvent(
            requester=requester(),
            confidence=0.8,
            signals=["canvas"],
            tracker_domains=["tracker.example"],
        )
    )

    assert quiet.outcome == Outcome.IGNORE
    assert quiet.risk == 0
    assert tracked.outcome == Outcome.INFORM
    assert tracked.risk == pytest.approx(0.432)
    assert "advertising profile" in " ".join(tracked.rationale)


def test_consent_dark_pattern_and_user_action_preference() -> None:
    preferences = UserPreferences(
        categories={"advertising": Preference.REJECT}, reject_optional_cookies=False
    )
    decision = decide(
        ConsentBannerEvent(
            requester=requester(),
            purposes=["necessary", "advertising"],
            dark_patterns=["hidden_reject"],
        ),
        preferences=preferences,
    )

    assert decision.outcome == Outcome.INTERVENE
    assert decision.risk >= 0.55
    assert decision.actions == ["view_details", "reject_optional", "continue"]
    assert decision.default_action == "view_details"
    rationale = " ".join(decision.rationale)
    assert "preference" in rationale
    assert "harder" in rationale


def test_broad_extension_history_access_intervenes() -> None:
    decision = decide(
        SystemAccessEvent(
            requester=Requester(
                kind="extension",
                display_name="Synthetic extension",
                purpose="wallpaper_utility",
                purpose_confidence=1,
            ),
            breadth=0.9,
            data_categories=[DataCategory.BROWSER_HISTORY],
        )
    )

    assert decision.outcome == Outcome.INTERVENE
    assert decision.risk >= 0.7
    assert any("browsing history" in note for note in decision.rationale)


@pytest.mark.parametrize(
    ("profile", "missing", "expected", "keyword"),
    [
        (
            SiteOrAppProfile(clauses=["ai_training", "retention_after_deletion"]),
            False,
            Outcome.INTERVENE,
            "ai training",
        ),
        (SiteOrAppProfile(), True, Outcome.INFORM, "No privacy policy"),
    ],
)
def test_policy_material_terms_and_missing_policy_are_visible(
    profile: SiteOrAppProfile, missing: bool, expected: Outcome, keyword: str
) -> None:
    decision = decide(
        PolicyDocumentEvent(requester=requester(), missing=missing),
        profile=profile,
    )

    assert decision.outcome == expected
    assert keyword in " ".join(decision.rationale)


def test_screen_activity_informs_but_denied_permission_is_ignored() -> None:
    active = decide(
        ScreenCaptureEvent(
            requester=requester("screen_recorder"),
            active=True,
            first_grant=False,
            data_categories=[DataCategory.SCREEN],
        )
    )
    denied = decide(
        PermissionRequestEvent(
            requester=requester(),
            permission="camera",
            state="denied",
            data_categories=[DataCategory.CAMERA],
        )
    )

    assert active.outcome == Outcome.INFORM
    assert any("now active" in note for note in active.rationale)
    assert denied.outcome == Outcome.IGNORE
    assert denied.explanation == "Access was denied or stopped. No active grant was detected."


def test_clipboard_writer_suppression_and_cloud_sync_warning() -> None:
    same_writer = decide(
        ClipboardReadEvent(
            requester=Requester(kind="application", bundle_id="test.writer"),
            writer_key="test.writer",
            data_categories=[DataCategory.FINANCIAL_CARD_NUMBER],
        )
    )
    cloud = decide(
        ClipboardReadEvent(
            requester=Requester(kind="application", bundle_id="test.reader"),
            writer_key="test.writer",
            cloud_sync=True,
            data_categories=[DataCategory.EMAIL],
        )
    )

    assert same_writer.outcome == Outcome.IGNORE
    assert cloud.outcome.value in {"INFORM", "INTERVENE"}
    assert any("cloud sync" in note for note in cloud.rationale)


def test_expected_and_requester_allow_overrides_respect_protected_data() -> None:
    identity = requester()
    expected = UserPreferences(
        expected_permissions={identity.key: [DataCategory.EMAIL]},
        requester_overrides={identity.key: "allow"},
    )
    email = decide(
        FileUploadEvent(requester=identity, data_categories=[DataCategory.EMAIL]),
        preferences=expected,
    )
    protected = decide(
        FileUploadEvent(
            requester=identity,
            data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT],
        ),
        preferences=UserPreferences(requester_overrides={identity.key: "allow"}),
    )

    assert email.outcome == Outcome.IGNORE
    assert protected.outcome != Outcome.IGNORE


def test_recent_equivalent_tracking_is_rate_limited_unless_confidence_jumps() -> None:
    now = datetime.now(UTC)
    event = TrackingEvent(
        requester=requester(),
        ts=now,
        confidence=0.5,
        signals=["canvas"],
        data_categories=[DataCategory.DEVICE_IDENTIFIERS],
    )
    seen = Observation(
        event_class="tracking",
        categories=[DataCategory.DEVICE_IDENTIFIERS],
        signals=["canvas"],
        confidence=0.5,
        ts=now - timedelta(minutes=5),
        answered=True,
    )
    profile = SiteOrAppProfile(recent_observations=[seen])
    repeated = decide(event, profile=profile)
    confidence_jump = decide(event.model_copy(update={"confidence": 0.8}), profile=profile)
    new_mechanism = decide(
        event.model_copy(update={"signals": ["canvas", "cname_cloaking"]}), profile=profile
    )
    unanswered = decide(
        event,
        profile=SiteOrAppProfile(recent_observations=[seen.model_copy(update={"answered": False})]),
    )

    assert repeated.outcome == Outcome.IGNORE
    assert any("last day" in note for note in repeated.rationale)
    assert confidence_jump.outcome == Outcome.INFORM
    # A mechanism that was not there last time is news, however recently the rest was shown.
    assert new_mechanism.outcome == Outcome.INFORM
    # Raised once and never answered is not "already dealt with": the person may
    # never have seen it, and silence for the rest of the day is not the answer.
    assert unanswered.outcome == Outcome.INFORM


def test_location_upload_offers_metadata_stripping_and_engine_delegates() -> None:
    event = FileUploadEvent(
        requester=requester("social"),
        data_categories=[DataCategory.LOCATION_PRECISE],
    )
    direct = decide(event)
    delegated = DecisionEngine().decide(event)

    assert direct.actions[0] == "strip_metadata"
    assert delegated == direct
