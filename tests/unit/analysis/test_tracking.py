from __future__ import annotations

from privacy_guardian.analysis.tracking import (
    CookieObservation,
    TrackingSnapshot,
    analyze_tracking,
    is_tracker,
    tracker_domain,
)


def test_tracker_domains_match_label_boundaries_only() -> None:
    assert is_tracker("doubleclick.net")
    assert is_tracker("ads.doubleclick.net")
    assert not is_tracker("doubleclick.net.evil.test")
    assert not is_tracker("notdoubleclick.net")


def test_tracker_heavy_snapshot_reports_profile_and_three_domains() -> None:
    analysis = analyze_tracking(
        TrackingSnapshot(
            origin="https://fixture.test",
            urls=[
                "https://doubleclick.net/pixel?gclid=synthetic",
                "https://connect.facebook.net/sync?email_hash=synthetic",
                "https://google-analytics.com/collect",
            ],
            request_hosts=[
                "doubleclick.net",
                "connect.facebook.net",
                "google-analytics.com",
            ],
            cookies=[
                CookieObservation(
                    domain=".doubleclick.net",
                    name="synthetic",
                    third_party=True,
                    lifetime_days=365,
                )
            ],
            api_calls=["canvas.fillText", "canvas.toDataURL"],
            storage_shared_identifiers=1,
            pixel_beacons=3,
            identity_sync=True,
        )
    )
    assert analysis.detected
    assert analysis.fingerprinting
    assert len(analysis.tracker_domains) >= 3
    assert {
        "persistent_third_party_cookies",
        "known_tracker_requests",
        "url_decoration",
        "fingerprinting",
        "cross_origin_storage_identifier",
        "tracking_pixels",
        "identity_linking",
    } <= set(analysis.signals)
    assert analysis.confidence >= 0.8
    assert "advertising profile" in analysis.summary.lower()


def test_clean_blog_snapshot_produces_no_event_signal() -> None:
    analysis = analyze_tracking(
        TrackingSnapshot(
            origin="https://clean-blog.test",
            urls=["https://clean-blog.test/article"],
            request_hosts=["clean-blog.test"],
            api_calls=["canvas.fillText"],
        )
    )
    assert not analysis.detected
    assert not analysis.fingerprinting
    assert analysis.tracker_domains == []
    assert analysis.confidence == 0


def test_enumeration_burst_and_audio_sequence_trigger_fingerprinting() -> None:
    enumeration = analyze_tracking(
        TrackingSnapshot(
            api_calls=[
                "navigator.plugins",
                "navigator.hardwareConcurrency",
                "navigator.deviceMemory",
            ]
        )
    )
    audio = analyze_tracking(TrackingSnapshot(api_calls=["AudioContext", "getFloatFrequencyData"]))
    assert enumeration.fingerprinting and enumeration.detected
    assert audio.fingerprinting and audio.detected


def test_short_lived_or_first_party_cookie_does_not_create_tracking_signal() -> None:
    for cookie in (
        CookieObservation(domain="doubleclick.net", third_party=True, lifetime_days=1),
        CookieObservation(domain="doubleclick.net", third_party=False, lifetime_days=365),
    ):
        analysis = analyze_tracking(TrackingSnapshot(cookies=[cookie]))
        assert not analysis.detected


def test_one_company_on_six_hostnames_is_counted_once() -> None:
    """Subdomains are how four advertising companies read as eleven websites."""
    hosts = [
        "ad.doubleclick.net",
        "cm.g.doubleclick.net",
        "securepubads.g.doubleclick.net",
        "b09567f6f3a32c6bbeb28c75e41cac69.safeframe.googlesyndication.com",
        "pagead2.googlesyndication.com",
        "www.google-analytics.com",
    ]
    analysis = analyze_tracking(
        TrackingSnapshot(
            origin="https://news.test",
            request_hosts=hosts,
            urls=[f"https://{host}/pixel?uid=synthetic" for host in hosts],
        )
    )

    assert analysis.tracker_domains == [
        "doubleclick.net",
        "google-analytics.com",
        "googlesyndication.com",
    ]


def test_a_host_outside_the_tracker_list_keeps_its_registrable_domain() -> None:
    assert tracker_domain("pixel.metrics-three.test") == "metrics-three.test"
    assert tracker_domain("beacon.stats.example.co.uk") == "example.co.uk"
    assert tracker_domain("criteo.com") == "criteo.com"
