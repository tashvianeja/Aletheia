from __future__ import annotations

import pytest

from aletheia.core.events import DataCategory
from aletheia.engine.context import SiteOrAppProfile
from aletheia.engine.necessity import Necessity, NecessityAssessment
from aletheia.engine.risk import consequence_factor, score_risk


def assessment(category: DataCategory, verdict: Necessity) -> NecessityAssessment:
    return NecessityAssessment(
        category=category,
        verdict=verdict,
        confidence=1.0,
        rationale="Independent synthetic assessment",
    )


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (Necessity.REQUIRED, 0.18),
        (Necessity.REASONABLE, 0.45),
        (Necessity.UNNECESSARY, 0.9),
        (Necessity.RED_FLAG, 1.0),
    ],
)
def test_risk_uses_specified_necessity_weights(
    monkeypatch, verdict: Necessity, expected: float
) -> None:
    monkeypatch.setattr(
        "aletheia.engine.risk.load_sensitivities",
        lambda: {DataCategory.FINANCIAL_CARD_NUMBER.value: 0.9},
    )
    result = score_risk([assessment(DataCategory.FINANCIAL_CARD_NUMBER, verdict)])
    assert result.risk == pytest.approx(expected)


def test_consequences_compound_and_risk_is_clamped(monkeypatch) -> None:
    monkeypatch.setattr(
        "aletheia.engine.risk.load_sensitivities",
        lambda: {DataCategory.PHONE.value: 0.5},
    )
    profile = SiteOrAppProfile(
        shares_with=["advertising_partners"],
        retention="after_deletion",
        training_on_user_content=True,
        international_transfer=True,
        data_sale=True,
        tracking_confidence=1.0,
    )
    result = score_risk([assessment(DataCategory.PHONE, Necessity.UNNECESSARY)], profile)
    assert consequence_factor(profile) == pytest.approx(1.25 * 1.2 * 1.15 * 1.1 * 1.3)
    assert result.tracking_boost == pytest.approx(0.3)
    assert result.risk == 1.0


def test_maximum_category_risk_drives_combined_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "aletheia.engine.risk.load_sensitivities",
        lambda: {DataCategory.EMAIL.value: 0.3, DataCategory.CREDENTIALS_PASSWORD.value: 1.0},
    )
    result = score_risk(
        [
            assessment(DataCategory.EMAIL, Necessity.REQUIRED),
            assessment(DataCategory.CREDENTIALS_PASSWORD, Necessity.RED_FLAG),
        ]
    )
    assert result.category_risks[DataCategory.EMAIL] == pytest.approx(0.06)
    assert result.category_risks[DataCategory.CREDENTIALS_PASSWORD] == 1.0
    assert result.risk == 1.0
