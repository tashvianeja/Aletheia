from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from privacy_guardian.analysis.policy.analyzer import patterns
from privacy_guardian.engine.necessity import purposes


class PolishedExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str
    rationale: list[str]


class RefinedPurpose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str
    confidence: float = Field(ge=0, le=1)
    rationale: str

    @field_validator("purpose")
    @classmethod
    def known_purpose(cls, value: str) -> str:
        if value not in {*purposes(), "unknown"}:
            raise ValueError("Unknown purpose category")
        return value


class RefinedClause(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    confidence: float = Field(ge=0, le=1)
    citation: str

    @field_validator("category")
    @classmethod
    def known_clause(cls, value: str) -> str:
        if value not in patterns():
            raise ValueError("Unknown policy clause category")
        return value


class RefinedPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clauses: list[RefinedClause]
    summary: str


class DeepCheckNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    findings: list[str]
    clean_checks: list[str]
