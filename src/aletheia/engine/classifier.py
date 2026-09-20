from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel

from aletheia.core.events import DataCategory, PrivacyEvent


class Classification(BaseModel):
    event_class: str
    sensitivities: dict[DataCategory, float]
    severity_prior: float


@lru_cache(maxsize=1)
def load_sensitivities() -> dict[str, float]:
    value: dict[str, float] = json.loads(
        files("aletheia.data").joinpath("sensitivity.yaml").read_text()
    )
    return value


def classify(event: PrivacyEvent) -> Classification:
    table = load_sensitivities()
    sensitivities = {category: table[category.value] for category in event.data_categories}
    return Classification(
        event_class=event.event_type,
        sensitivities=sensitivities,
        severity_prior=max(sensitivities.values(), default=0.0),
    )
