from __future__ import annotations

from datetime import timedelta

from privacy_guardian.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    Decision,
    FileUploadEvent,
    Finding,
    FormObservedEvent,
    FormSubmitEvent,
    Outcome,
    PermissionRequestEvent,
    PolicyDocumentEvent,
    PrivacyEvent,
    ScreenCaptureEvent,
    SystemAccessEvent,
    TrackingEvent,
)
from privacy_guardian.engine.context import SiteOrAppProfile, analyze_context
from privacy_guardian.engine.explain import explain
from privacy_guardian.engine.necessity import Necessity
from privacy_guardian.engine.preferences import LearnedRules, Preference, UserPreferences, protected
from privacy_guardian.engine.risk import score_risk

_LEVELS = [Outcome.IGNORE, Outcome.INFORM, Outcome.INTERVENE]
_ACTIONS: dict[str, tuple[list[str], str]] = {
    "file_upload": (["cancel", "continue", "redact"], "cancel"),
    "form_submit": (["cancel", "continue", "review_fields"], "cancel"),
    "form_observed": (["review_fields", "continue"], "review_fields"),
    "consent_banner": (["reject_optional", "continue", "view_details"], "reject_optional"),
    "tracking": (["block", "learn_more"], "block"),
    "permission_request": (["open_settings", "mark_expected"], "open_settings"),
    "system_access": (["open_settings", "mark_expected"], "open_settings"),
    "screen_capture": (["open_settings", "mark_expected"], "open_settings"),
    "startup_registration": (["open_settings", "mark_expected"], "open_settings"),
    "clipboard_read": (["clear_clipboard", "open_settings", "continue"], "clear_clipboard"),
    "policy_document": (["cancel", "continue", "view_details"], "cancel"),
}


def decide(
    event: PrivacyEvent,
    findings: list[Finding] | None = None,
    profile: SiteOrAppProfile | None = None,
    preferences: UserPreferences | None = None,
    learned_rules: LearnedRules | None = None,
) -> Decision:
    profile = profile or SiteOrAppProfile()
    preferences = preferences or UserPreferences()
    learned_rules = learned_rules or LearnedRules()
    categories = set(event.data_categories) | {finding.category for finding in findings or []}
    if isinstance(event, FormObservedEvent):
        categories |= {
            field.category
            for field in event.fields
            if field.category is not None
            and (not isinstance(event, FormSubmitEvent) or field.filled)
        }
    event = event.model_copy(update={"data_categories": sorted(categories, key=str)})
    assessments = analyze_context(event.requester, event.data_categories)
    scored = score_risk(assessments, profile, learned_rules, event.requester.purpose)
    risk = scored.risk
    level = 0 if risk < 0.25 else 1 if risk < 0.55 else 2
    notes: list[str] = []
    if categories and all(
        preferences.for_category(category) == Preference.USUALLY_ALLOW for category in categories
    ):
        level = 0 if risk < 0.45 else 1 if risk < 0.75 else 2
    minimum = 0
    for category in categories:
        preference = preferences.for_category(category)
        if preference == Preference.ALWAYS_WARN:
            minimum = max(minimum, 2 if scored.category_risks.get(category, 0) >= 0.4 else 1)
        elif preference == Preference.REJECT:
            minimum = max(minimum, 1)
    level = max(level, minimum)
    high_impact = any(protected(category) for category in categories)
    if isinstance(event, TrackingEvent):
        risk = (
            max(0.25, min(0.54, event.confidence * 0.54))
            if event.signals or event.tracker_domains or event.fingerprinting
            else 0.0
        )
        level = max(minimum, 1 if risk else 0)
        notes.append("Persistent identifiers may link your activity into an advertising profile.")
    if isinstance(event, ConsentBannerEvent):
        optional = any(p != "necessary" for p in event.purposes)
        rejects_tracking = (
            preferences.categories.get("analytics") == Preference.REJECT
            or preferences.categories.get("advertising") == Preference.REJECT
        )
        if optional and rejects_tracking:
            notes.append("Your preference is to reject optional analytics and advertising cookies.")
        risk = max(
            risk,
            0.55
            if event.dark_patterns
            else 0.3
            if any(p != "necessary" for p in event.purposes)
            else 0,
        )
        level = max(level, 2 if event.dark_patterns else 1 if risk >= 0.25 else 0)
        if event.dark_patterns:
            notes.append(
                "The consent design makes rejecting optional tracking harder than accepting it."
            )
    if (
        isinstance(event, SystemAccessEvent)
        and event.breadth >= 0.6
        and any(item.verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG} for item in assessments)
    ):
        risk = max(risk, 0.65)
        level = max(level, 2)
        notes.append("The breadth of system access exceeds what this task appears to need.")
    if (
        isinstance(event, SystemAccessEvent)
        and event.requester.kind == "extension"
        and event.breadth >= 0.6
        and DataCategory.BROWSER_HISTORY in categories
    ):
        risk = max(risk, 0.7)
        level = max(level, 2)
        notes.append(
            "This extension can access browsing history and broad website activity; review whether it needs that breadth of access."
        )
    if isinstance(event, PolicyDocumentEvent):
        material = set(profile.clauses)
        if material:
            risk = max(risk, 0.6)
            level = max(level, 2)
            notes.append(
                "The agreement contains: "
                + ", ".join(clause.replace("_", " ") for clause in sorted(material))
                + "."
            )
        elif event.missing or profile.policy_missing:
            risk = max(risk, 0.3)
            level = max(level, 1)
            notes.append(
                "No privacy policy found; collection and retention terms could not be checked."
            )
    if isinstance(event, ScreenCaptureEvent) and event.active and not event.first_grant:
        level = max(minimum, 1)
        notes.append("Screen capture is now active.")
    if isinstance(event, PermissionRequestEvent) and event.state in {"denied", "stopped"}:
        level = 0
    if isinstance(event, FormObservedEvent) and event.event_type == "form_observed":
        level = min(level, 1)
    if (
        isinstance(event, ClipboardReadEvent)
        and not event.cloud_sync
        and (
            event.writer_key == event.requester.key
            or event.requester.key in preferences.clipboard_allowlist
        )
    ):
        level = 0
    if isinstance(event, ClipboardReadEvent) and event.cloud_sync and categories:
        risk = max(risk, 0.3)
        level = max(level, 1)
        notes.append(
            "Operating-system clipboard cloud sync is enabled; sensitive clipboard content may be copied to other devices."
        )
    expected = set(preferences.expected_permissions.get(event.requester.key, []))
    if categories and categories <= expected:
        level = 0 if not high_impact else min(level, 1)
        notes.append("You marked this access as expected for this application.")
    if preferences.requester_overrides.get(event.requester.key) == "allow" and not high_impact:
        level = 0
        notes.append("You explicitly allowed this requester.")
    learned_floor = 0
    if (
        level == 2
        and not high_impact
        and categories
        and all(
            learned_rules.allows_downgrade(category, event.requester.purpose)
            for category in categories
        )
    ):
        level = 1
        learned_floor = 1
        notes.append(
            "You continued at least three times for this data and purpose; this reminder remains visible."
        )
    red_flags = {item.category for item in assessments if item.verdict == Necessity.RED_FLAG}
    for observation in profile.recent_observations:
        if observation.event_class and observation.event_class != event.event_type:
            continue
        if isinstance(event, ConsentBannerEvent) and set(event.dark_patterns) - set(
            observation.signals
        ):
            continue
        if isinstance(event, PolicyDocumentEvent) and set(profile.clauses) - set(
            observation.signals
        ):
            continue
        if set(observation.categories) != categories or not timedelta(
            0
        ) <= event.ts - observation.ts < timedelta(hours=24):
            continue
        if high_impact or red_flags - set(observation.red_flags):
            continue
        if (
            isinstance(event, TrackingEvent)
            and event.confidence - observation.confidence >= 0.2 - 1e-9
        ):
            continue
        level = max(minimum, level - 1)
        notes.append("The same request was already shown within the last day.")
        break
    level = max(level, learned_floor)
    partial_upload = isinstance(event, FileUploadEvent) and event.partial
    if partial_upload:
        level = max(level, 1)
        risk = max(risk, 0.25)
        notes.append("Partial file analysis: omitted or unreadable content has not been checked.")
    actions, default_action = _ACTIONS.get(
        event.event_type, (["open_settings", "continue"], "open_settings")
    )
    actions = list(actions)
    if isinstance(event, ConsentBannerEvent) and not preferences.reject_optional_cookies:
        actions = ["view_details", "reject_optional", "continue"]
        default_action = "view_details"
    if event.event_type == "file_upload" and DataCategory.LOCATION_PRECISE in categories:
        actions.insert(0, "strip_metadata")
    explanation, rationale = explain(event, assessments, profile, notes)
    if partial_upload:
        explanation = (
            "This file was only partially checked; " + explanation[:1].lower() + explanation[1:]
        )
    if isinstance(event, PermissionRequestEvent) and event.state in {"denied", "stopped"}:
        level = 0
        explanation = "Access was denied or stopped; no active grant was detected."
        rationale.append(explanation)
    return Decision(
        event_id=event.id,
        outcome=_LEVELS[level],
        risk=risk,
        explanation=explanation,
        rationale=rationale,
        actions=actions,
        default_action=default_action,
    )


class DecisionEngine:
    def decide(
        self,
        event: PrivacyEvent,
        findings: list[Finding] | None = None,
        profile: SiteOrAppProfile | None = None,
        preferences: UserPreferences | None = None,
        learned_rules: LearnedRules | None = None,
    ) -> Decision:
        return decide(event, findings, profile, preferences, learned_rules)
