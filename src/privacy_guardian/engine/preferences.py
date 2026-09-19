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
    # Actions the user has explicitly authorised Privacy Guardian to take without asking.
    automatic_actions: list[str] = Field(default_factory=list)

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


# Only choices that are reversible and never high-impact may ever become automatic.
AUTOMATABLE: dict[str, str] = {
    "reject_optional": "reject optional cookies",
    "block": "block advertising identifiers",
}
SUGGEST_AFTER_SITES = 5


class LearnedRules(BaseModel):
    rules: list[LearnedRule] = Field(default_factory=list)
    # Distinct sites or apps where the same protective choice was made.
    action_sites: dict[str, list[str]] = Field(default_factory=dict)
    # Offers already made, so the same question is never asked twice.
    suggested: list[str] = Field(default_factory=list)
    declined: list[str] = Field(default_factory=list)

    def observe(self, action: str, requester_key: str) -> None:
        if action not in AUTOMATABLE or not requester_key:
            return
        sites = self.action_sites.setdefault(action, [])
        if requester_key not in sites:
            sites.append(requester_key)
            del sites[:-50]

    def suggestion(self, already_automatic: list[str]) -> str:
        """The one repeated choice worth offering to make automatic, if any."""
        for action, sites in self.action_sites.items():
            if (
                len(sites) >= SUGGEST_AFTER_SITES
                and action not in self.suggested
                and action not in self.declined
                and action not in already_automatic
            ):
                return action
        return ""

    def site_count(self, action: str) -> int:
        return len(self.action_sites.get(action, []))

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
        self.action_sites.clear()
        self.suggested.clear()
        self.declined.clear()


def learn(
    rules: LearnedRules, categories: list[DataCategory], purpose: str, action: str
) -> LearnedRules:
    result = rules.model_copy(deep=True)
    for category in categories:
        result.record(category, purpose, action)
    return result
