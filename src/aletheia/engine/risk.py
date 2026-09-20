from __future__ import annotations

from pydantic import BaseModel, Field

from aletheia.core.events import DataCategory
from aletheia.engine.classifier import load_sensitivities
from aletheia.engine.context import SiteOrAppProfile
from aletheia.engine.necessity import NecessityAssessment
from aletheia.engine.preferences import LearnedRules

WEIGHTS = {"required": 0.2, "reasonable": 0.5, "unnecessary": 1.0, "red_flag": 1.3}


class RiskResult(BaseModel):
    risk: float
    category_risks: dict[DataCategory, float] = Field(default_factory=dict)
    consequence: float = 1.0
    tracking_boost: float = 0.0
    unexpectedness: float = 0.0


def consequence_factor(profile: SiteOrAppProfile) -> float:
    factor = 1.0
    if set(profile.shares_with) & {"advertising_partners", "data_brokers"}:
        factor *= 1.25
    if profile.retention == "after_deletion":
        factor *= 1.2
    if profile.training_on_user_content or "ai_training" in profile.purposes:
        factor *= 1.15
    if profile.international_transfer:
        factor *= 1.1
    if profile.data_sale:
        factor *= 1.3
    return factor


def score_risk(
    assessments: list[NecessityAssessment],
    profile: SiteOrAppProfile | None = None,
    learned_rules: LearnedRules | None = None,
    purpose: str = "unknown",
) -> RiskResult:
    profile = profile or SiteOrAppProfile()
    factor = consequence_factor(profile)
    boost = min(0.3, max(0.0, profile.tracking_confidence) * 0.3)
    table = load_sensitivities()
    values = {
        item.category: min(
            1.0, table[item.category.value] * WEIGHTS[item.verdict.value] * factor * (1 + boost)
        )
        for item in assessments
    }
    unexpected = 0.0
    if learned_rules and values:
        unexpected = sum(
            not learned_rules.allows_downgrade(category, purpose) for category in values
        ) / len(values)
    return RiskResult(
        risk=max(values.values(), default=0),
        category_risks=values,
        consequence=factor,
        tracking_boost=boost,
        unexpectedness=unexpected,
    )
