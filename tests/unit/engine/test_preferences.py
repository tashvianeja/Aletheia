from __future__ import annotations

from aletheia.core.events import DataCategory
from aletheia.engine.preferences import (
    LearnedRules,
    Preference,
    UserPreferences,
    learn,
)


def test_defaults_match_product_spec() -> None:
    preferences = UserPreferences()
    assert preferences.for_category(DataCategory.MEDICAL_DIAGNOSIS) == Preference.ALWAYS_WARN
    assert preferences.for_category(DataCategory.GOVERNMENT_ID_PASSPORT) == Preference.ALWAYS_WARN
    assert preferences.for_category(DataCategory.LOCATION_PRECISE) == Preference.ASK
    assert preferences.for_category(DataCategory.PHONE) == Preference.ASK
    assert preferences.for_category(DataCategory.EMAIL) == Preference.USUALLY_ALLOW
    assert preferences.categories["analytics"] == Preference.REJECT
    assert preferences.categories["advertising"] == Preference.REJECT


def test_three_consecutive_continue_decisions_activate_unprotected_rule() -> None:
    rules = LearnedRules()
    for _ in range(3):
        rules = learn(rules, [DataCategory.PHONE], "saas_b2b", "continue")
    assert rules.allows_downgrade(DataCategory.PHONE, "saas_b2b")


def test_non_continue_resets_consecutive_learning() -> None:
    rules = LearnedRules()
    for action in ("continue", "continue", "cancel", "continue"):
        rules = learn(rules, [DataCategory.PHONE], "saas_b2b", action)
    assert not rules.allows_downgrade(DataCategory.PHONE, "saas_b2b")
    assert rules.rules[0].total_decisions == 4
    assert rules.rules[0].consecutive_continue == 1


def test_protected_categories_never_activate_auto_downgrade() -> None:
    protected = (
        DataCategory.GOVERNMENT_ID_PASSPORT,
        DataCategory.MEDICAL_DIAGNOSIS,
        DataCategory.FINANCIAL_CARD_NUMBER,
        DataCategory.CREDENTIALS_PASSWORD,
        DataCategory.BIOMETRIC_PHOTO,
        DataCategory.MINORS_DATA,
    )
    rules = LearnedRules()
    for _ in range(10):
        rules = learn(rules, list(protected), "anything", "continue")
    assert all(not rules.allows_downgrade(category, "anything") for category in protected)


def test_preferences_import_export_round_trip() -> None:
    original = UserPreferences(
        requester_overrides={"https://example.test": "allow"},
        clipboard_allowlist=["com.synthetic.writer"],
        reject_optional_cookies=False,
    )
    assert UserPreferences.import_json(original.export_json()) == original
