from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel

from privacy_guardian.core.events import DataCategory


class Necessity(StrEnum):
    REQUIRED = "required"
    REASONABLE = "reasonable"
    UNNECESSARY = "unnecessary"
    RED_FLAG = "red_flag"


class NecessityAssessment(BaseModel):
    category: DataCategory
    verdict: Necessity
    confidence: float
    rationale: str


@lru_cache(maxsize=1)
def load_matrix() -> dict[str, dict[str, object]]:
    value: dict[str, dict[str, object]] = json.loads(
        files("privacy_guardian.data").joinpath("necessity_matrix.yaml").read_text()
    )
    return value


def purposes() -> tuple[str, ...]:
    return tuple(load_matrix())


def necessity_for(
    purpose: str, category: DataCategory | str, purpose_confidence: float = 1.0
) -> NecessityAssessment:
    category = DataCategory(category)
    entry = load_matrix().get(purpose)
    label = category.value.replace(".", " ").replace("_", " ")
    if entry is None or purpose_confidence < 0.35:
        return NecessityAssessment(
            category=category,
            verdict=Necessity.REASONABLE,
            confidence=0.2,
            rationale=f"The purpose is uncertain, so whether {label} is necessary is not yet known.",
        )
    vector = entry["categories"]
    if not isinstance(vector, dict):
        raise ValueError("Invalid necessity matrix")
    verdict = Necessity(vector[category.value])
    description = {
        "required": "is needed",
        "reasonable": "may reasonably be used",
        "unnecessary": "does not appear necessary",
        "red_flag": "is unusually sensitive and does not appear necessary",
    }[verdict.value]
    return NecessityAssessment(
        category=category,
        verdict=verdict,
        confidence=max(0.0, min(1.0, purpose_confidence)),
        rationale=f"{label.capitalize()} {description} for a {purpose.replace('_', ' ')}.",
    )


assess_necessity = necessity_for
