from __future__ import annotations

from privacy_guardian.core.events import PrivacyEvent
from privacy_guardian.engine.context import SiteOrAppProfile
from privacy_guardian.engine.necessity import NecessityAssessment

LABELS = {
    "government_id.passport": "passport information",
    "dob": "date of birth",
    "biometric_photo": "identity photo",
    "files_broad": "access to all files",
    "screen": "screen recording",
    "financial.card_number": "card number",
    "location_precise": "precise location",
    "device_identifiers": "persistent device identifiers",
}


def category_label(value: str) -> str:
    return LABELS.get(value, value.replace(".", " ").replace("_", " "))


def explain(
    event: PrivacyEvent,
    assessments: list[NecessityAssessment],
    profile: SiteOrAppProfile,
    notes: list[str] | None = None,
) -> tuple[str, list[str]]:
    labels = (
        ", ".join(category_label(item.category.value) for item in assessments[:4])
        or "privacy-related access"
    )
    who = event.requester.display_name or event.requester.origin or "This service"
    purpose = event.requester.purpose.replace("_", " ")
    uncertain = event.requester.purpose == "unknown" or event.requester.purpose_confidence < 0.35
    first = f"{who} is requesting {labels}."
    second = (
        "Its purpose is uncertain, so necessity could not be confirmed."
        if uncertain
        else f"This looks like a {purpose}; "
    )
    if not uncertain:
        unnecessary = [
            category_label(item.category.value)
            for item in assessments
            if item.verdict in {"unnecessary", "red_flag"}
        ]
        second += (
            ", ".join(unnecessary[:3]) + " does not appear necessary for that task."
            if unnecessary
            else "these categories appear relevant to that task."
        )
    effects = []
    if profile.retention == "after_deletion":
        effects.append("data may be kept after account deletion")
    if set(profile.shares_with) & {"advertising_partners", "data_brokers"}:
        effects.append("data may be shared with advertisers or data brokers")
    if profile.training_on_user_content:
        effects.append("content may be used for AI training")
    third = ("The policy says " + "; ".join(effects) + ".") if effects else ""
    rationale = [item.rationale for item in assessments]
    rationale.extend(notes or [])
    if effects:
        rationale.append(third)
    if not third and notes:
        third = notes[-1]
    return " ".join(part for part in (first, second, third) if part), rationale
