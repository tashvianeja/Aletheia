from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from privacy_guardian.core.events import DataCategory


class Preference(StrEnum):
    ALWAYS_WARN = "always_warn"
    ASK = "ask"
    USUALLY_ALLOW = "usually_allow"
    REJECT = "reject"


NEVER_AUTO_DOWNGRADE = frozenset(
    {"government_id", "medical", "financial", "credentials", "biometric_photo", "minors_data"}
)


def protected(category: DataCategory | str) -> bool:
    return str(category).split(".")[0] in NEVER_AUTO_DOWNGRADE


def default_categories() -> dict[str, Preference]:
    return {
        "medical": Preference.ALWAYS_WARN,
        "government_id": Preference.ALWAYS_WARN,
        "location_precise": Preference.ASK,
        "location_coarse": Preference.ASK,
        "phone": Preference.ASK,
        "email": Preference.USUALLY_ALLOW,
        "analytics": Preference.REJECT,
        "advertising": Preference.REJECT,
    }


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: dict[str, Preference] = Field(default_factory=default_categories)
    requester_overrides: dict[str, str] = Field(default_factory=dict)
    expected_permissions: dict[str, list[DataCategory]] = Field(default_factory=dict)
    clipboard_allowlist: list[str] = Field(default_factory=list)
    reject_optional_cookies: bool = True

    def for_category(self, category: DataCategory) -> Preference:
        return self.categories.get(
            category.value, self.categories.get(category.value.split(".")[0], Preference.ASK)
        )

    def export_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def import_json(cls, value: str) -> UserPreferences:
        return cls.model_validate_json(value)


class LearnedRule(BaseModel):
    category: DataCategory
    purpose: str
    consecutive_continue: int = Field(default=0, ge=0)
    total_decisions: int = Field(default=0, ge=0)

    @property
    def active(self) -> bool:
        return self.consecutive_continue >= 3 and not protected(self.category)


class LearnedRules(BaseModel):
    rules: list[LearnedRule] = Field(default_factory=list)

    def allows_downgrade(self, category: DataCategory, purpose: str) -> bool:
        return any(
            rule.category == category and rule.purpose == purpose and rule.active
            for rule in self.rules
        )

    def record(self, category: DataCategory, purpose: str, action: str) -> None:
        rule = next(
            (rule for rule in self.rules if rule.category == category and rule.purpose == purpose),
            None,
        )
        if rule is None:
            rule = LearnedRule(category=category, purpose=purpose)
            self.rules.append(rule)
        rule.total_decisions += 1
        rule.consecutive_continue = rule.consecutive_continue + 1 if action == "continue" else 0

    def reset(self) -> None:
        self.rules.clear()


def learn(
    rules: LearnedRules, categories: list[DataCategory], purpose: str, action: str
) -> LearnedRules:
    result = rules.model_copy(deep=True)
    for category in categories:
        result.record(category, purpose, action)
    return result
