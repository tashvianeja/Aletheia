from __future__ import annotations

from privacy_guardian.core.events import (
    ConsentBannerEvent,
    DataCategory,
    FileUploadEvent,
    FormContext,
    FormField,
    FormObservedEvent,
    FormSubmitEvent,
    PermissionRequestEvent,
    Requester,
    TrackingEvent,
)
from privacy_guardian.engine.notice import notice_signature

SITE = Requester(origin="https://news.example", display_name="news.example")


def tracking(signals: list[str], domains: list[str], fingerprinting: bool = False) -> TrackingEvent:
    return TrackingEvent(
        requester=SITE,
        signals=signals,
        tracker_domains=domains,
        fingerprinting=fingerprinting,
        confidence=0.35 + 0.12 * len(signals),
    )


def test_tracking_waves_on_one_page_are_all_the_same_notice() -> None:
    """What a page is doing arrives in instalments; it is still one thing to say."""
    first = tracking(["known_tracker_requests"], ["pagead2.googlesyndication.com"])
    later = tracking(
        ["known_tracker_requests", "tracking_pixels", "fingerprinting"],
        ["pagead2.googlesyndication.com", "doubleclick.net", "cm.g.doubleclick.net"],
        fingerprinting=True,
    )
    assert notice_signature(first) == notice_signature(later)


def test_each_site_gets_its_own_tracking_notice() -> None:
    other = Requester(origin="https://shop.example", display_name="shop.example")
    here = tracking(["known_tracker_requests"], ["doubleclick.net"])
    there = TrackingEvent(requester=other, signals=["known_tracker_requests"])
    assert notice_signature(here) != notice_signature(there)


def test_tracking_is_not_confused_with_another_warning_about_the_same_site() -> None:
    consent = ConsentBannerEvent(requester=SITE, cmp="onetrust", purposes=["advertising"])
    assert notice_signature(tracking(["known_tracker_requests"], [])) != notice_signature(consent)


def test_a_consent_banner_that_reveals_a_dark_pattern_is_a_different_notice() -> None:
    plain = ConsentBannerEvent(requester=SITE, cmp="onetrust", purposes=["advertising"])
    hidden_reject = ConsentBannerEvent(
        requester=SITE, cmp="onetrust", purposes=["advertising"], dark_patterns=["hidden_reject"]
    )
    assert notice_signature(plain) != notice_signature(hidden_reject)


def test_a_permission_that_changes_state_is_a_different_notice() -> None:
    requested = PermissionRequestEvent(requester=SITE, permission="camera", state="requested")
    granted = PermissionRequestEvent(requester=SITE, permission="camera", state="granted")
    assert notice_signature(requested) != notice_signature(granted)


def test_every_upload_is_asked_about_on_its_own() -> None:
    assert notice_signature(FileUploadEvent(requester=SITE, filename="passport.pdf")) == ""


def observed(fields: list[FormField]) -> FormObservedEvent:
    return FormObservedEvent(
        requester=SITE,
        fields=fields,
        data_categories=sorted({field.category for field in fields if field.category}, key=str),
        context=FormContext(heading="Customer feedback survey", submit_text="Submit"),
    )


def test_a_form_reporting_itself_on_every_keystroke_is_one_notice() -> None:
    """The card offering to redact a form's fields must not arrive once per keystroke.

    The page re-inventories its fields whenever one of them changes, so what makes this
    one card rather than a column of them is that every pass over the same form carries
    the same signature, and the service hands them all the same event id.
    """
    empty = observed(
        [
            FormField(field_id="f1", category=DataCategory.CREDENTIALS_PASSWORD),
            FormField(field_id="f2", category=DataCategory.FINANCIAL_CARD_NUMBER),
        ]
    )
    typed = observed(
        [
            FormField(field_id="f1", category=DataCategory.CREDENTIALS_PASSWORD, filled=True),
            FormField(field_id="f2", category=DataCategory.FINANCIAL_CARD_NUMBER, filled=True),
        ]
    )
    assert notice_signature(empty) == notice_signature(typed) != ""


def test_submitting_a_form_is_always_asked_afresh() -> None:
    """Observing a form is a standing state; sending one holds up a real action, and
    reusing an earlier answer for it would send what was refused last time."""
    submitted = FormSubmitEvent(
        requester=SITE,
        fields=[FormField(field_id="f1", category=DataCategory.CREDENTIALS_PASSWORD, filled=True)],
    )
    assert notice_signature(submitted) == ""


def test_two_forms_asking_for_different_things_are_different_notices() -> None:
    card = observed([FormField(field_id="f1", category=DataCategory.FINANCIAL_CARD_NUMBER)])
    passport = observed([FormField(field_id="f1", category=DataCategory.GOVERNMENT_ID_PASSPORT)])
    assert notice_signature(card) != notice_signature(passport)
