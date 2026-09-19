from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from privacy_guardian.core.events import DataCategory, Requester
from privacy_guardian.engine.necessity import NecessityAssessment, necessity_for


class Observation(BaseModel):
    event_class: str = ""
    signals: list[str] = Field(default_factory=list)
    categories: list[DataCategory] = Field(default_factory=list)
    ts: datetime
    red_flags: list[DataCategory] = Field(default_factory=list)
    confidence: float = 0.0
    # Which notice this came from, so the person's answer can be recorded against it.
    event_id: str = ""
    # Whether they ever did anything with it. A warning that was raised is not a
    # warning that was read: quieting one nobody answered is how a site that tracks
    # you goes silent for a day after a single card the person may never have seen.
    answered: bool = False


class SiteOrAppProfile(BaseModel):
    shares_with: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    retention: str = "unspecified"
    training_on_user_content: bool = False
    international_transfer: bool = False
    data_sale: bool = False
    tracking_confidence: float = 0.0
    dark_patterns: list[str] = Field(default_factory=list)
    clauses: list[str] = Field(default_factory=list)
    recent_observations: list[Observation] = Field(default_factory=list)
    policy_missing: bool = False


def analyze_context(
    requester: Requester, categories: list[DataCategory]
) -> list[NecessityAssessment]:
    return [
        necessity_for(requester.purpose, category, requester.purpose_confidence)
        for category in categories
    ]
