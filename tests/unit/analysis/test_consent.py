from __future__ import annotations

import pytest

from aletheia.analysis.consent import (
    ConsentButton,
    ConsentSnapshot,
    ConsentToggle,
    analyze_consent,
    cmp_adapters,
)


@pytest.mark.parametrize("cmp", ["onetrust", "cookiebot", "quantcast", "trustarc", "didomi"])
def test_known_cmp_layout_is_detected_and_has_reject_action(cmp: str) -> None:
    adapter = cmp_adapters()[cmp]
    analysis = analyze_consent(
        ConsentSnapshot(
            selectors=[adapter["selectors"][0]],
            text="Necessary, analytics and advertising cookies",
            buttons=[ConsentButton(text="Accept all", role="accept")],
        )
    )
    assert analysis.detected
    assert analysis.cmp == cmp
    assert analysis.reject_selectors == adapter["reject"]
    assert {"necessary", "analytics", "advertising"} <= set(analysis.purposes)


def test_hidden_reject_is_flagged_but_symmetric_choice_is_not() -> None:
    hidden = analyze_consent(
        ConsentSnapshot(
            fixed_or_sticky=True,
            text="Cookie consent",
            buttons=[ConsentButton(text="Accept all", role="accept", area=4000, contrast=7)],
        )
    )
    symmetric = analyze_consent(
        ConsentSnapshot(
            fixed_or_sticky=True,
            text="Cookie consent",
            buttons=[
                ConsentButton(text="Accept all", role="accept", area=4000, contrast=7),
                ConsentButton(text="Reject optional", role="reject", area=4000, contrast=7),
            ],
        )
    )
    assert "reject_absent_first_layer" in hidden.dark_patterns
    assert symmetric.dark_patterns == []


def test_all_dark_pattern_signals_are_reported_once() -> None:
    analysis = analyze_consent(
        ConsentSnapshot(
            fixed_or_sticky=True,
            text="Cookie consent. No thanks, I prefer bad recommendations.",
            buttons=[
                ConsentButton(text="Accept all", role="accept", area=5000, contrast=8),
                ConsentButton(text="Reject", role="reject", area=1000, contrast=2),
            ],
            toggles=[
                ConsentToggle(purpose="analytics", enabled=True),
                ConsentToggle(purpose="advertising", enabled=True, legitimate_interest=True),
            ],
            reject_clicks=2,
        )
    )
    assert set(analysis.dark_patterns) == {
        "reject_visually_deemphasised",
        "preticked_optional",
        "legitimate_interest_default_on",
        "confirmshaming",
        "layered_rejection",
    }
    assert len(analysis.dark_patterns) == len(set(analysis.dark_patterns))


def test_tcf_snapshot_maps_purposes_and_vendor_count() -> None:
    analysis = analyze_consent(
        ConsentSnapshot(
            tcf_present=True,
            tcf_purpose_consents={"1": True, "2": True, "7": False},
            tcf_vendor_count=187,
        )
    )
    assert analysis.detected
    assert analysis.vendor_count == 187
    assert set(analysis.purposes) == {"necessary", "advertising", "analytics"}
    assert analysis.dark_patterns == ["preticked_optional"]


def test_ordinary_non_banner_content_is_not_detected() -> None:
    analysis = analyze_consent(
        ConsentSnapshot(
            text="This article explains how browser cookies work.",
            buttons=[ConsentButton(text="Read more")],
        )
    )
    assert not analysis.detected
    assert analysis.dark_patterns == []


def test_a_toggle_label_is_folded_into_the_purpose_it_names() -> None:
    """ "Targeted advertising" is the advertising purpose, not a fifth one to list."""
    analysis = analyze_consent(
        ConsentSnapshot(
            text="We use cookies.",
            cmp="onetrust",
            fixed_or_sticky=True,
            buttons=[ConsentButton(text="Accept all")],
            toggles=[
                ConsentToggle(purpose="Targeted advertising", enabled=True),
                ConsentToggle(purpose="Site analytics", enabled=True),
                ConsentToggle(purpose="Partner surveys", enabled=True),
            ],
        )
    )

    assert "advertising" in analysis.purposes
    assert "analytics" in analysis.purposes
    assert "Targeted advertising" not in analysis.purposes
    # A label that matches no known purpose is kept as the site worded it.
    assert "Partner surveys" in analysis.purposes
