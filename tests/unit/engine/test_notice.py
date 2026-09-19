from __future__ import annotations

from privacy_guardian.core.events import (
    ConsentBannerEvent,
    FileUploadEvent,
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
