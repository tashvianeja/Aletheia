from __future__ import annotations

from typing import Literal

from privacy_guardian.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    DecisionFinding,
    FileUploadEvent,
    FormObservedEvent,
    PermissionRequestEvent,
    PolicyDocumentEvent,
    PrivacyEvent,
    ScreenCaptureEvent,
    SystemAccessEvent,
    TrackingEvent,
)
from privacy_guardian.engine.context import SiteOrAppProfile
from privacy_guardian.engine.necessity import Necessity, NecessityAssessment

LABELS = {
    "government_id": "Government ID",
    "government_id.passport": "Passport number",
    "government_id.national_id": "National ID number",
    "government_id.ssn": "Social security number",
    "government_id.drivers_license": "Driving licence number",
    "government_id.tax_id": "Tax identification number",
    "full_name": "Full name",
    "dob": "Date of birth",
    "age": "Age",
    "gender": "Gender",
    "email": "Email",
    "phone": "Phone number",
    "postal_address": "Home address",
    "biometric_photo": "Photo",
    "financial": "Financial details",
    "financial.card_number": "Card number",
    "financial.iban": "Bank account (IBAN)",
    "financial.account_number": "Bank account number",
    "financial.routing": "Bank routing number",
    "medical": "Medical information",
    "medical.diagnosis": "Medical diagnosis",
    "medical.medication": "Medication",
    "medical.insurance_id": "Health insurance ID",
    "credentials": "Credentials",
    "credentials.password": "Password",
    "credentials.api_key": "API key",
    "credentials.private_key": "Private key",
    "location_precise": "Precise location",
    "location_coarse": "Approximate location",
    "device_identifiers": "Persistent device identifiers",
    "browsing_activity": "Browsing activity",
    "browser_history": "Browser history",
    "contacts": "Contacts",
    "calendar": "Calendar",
    "files_broad": "Full file access",
    "camera": "Camera",
    "microphone": "Microphone",
    "screen": "Screen recording",
    "clipboard": "Clipboard",
    "accessibility": "Accessibility control",
    "automation": "System automation",
    "background_execution": "Background execution",
    "startup": "Startup access",
    "employment": "Employment history",
    "education": "Education history",
    "ethnicity_religion_orientation": "Ethnicity, religion or orientation",
    "minors_data": "Information about a child",
    "free_text_pii": "Personal details in free text",
}

# The second half of a finding row: "Full file access — can read every file on this computer".
CONSEQUENCES = {
    "files_broad": "can read every file on this computer",
    "startup": "runs every time you log in",
    "background_execution": "keeps running when closed",
    "screen": "can record everything you see",
    "accessibility": "can read and control any window",
    "automation": "can drive other applications for you",
    "clipboard": "can read anything you copy",
    "browser_history": "can read every page you have visited",
    "browsing_activity": "can watch what you do across websites",
    "device_identifiers": "can recognise you on return visits",
    "camera": "can see you at any time",
    "microphone": "can listen at any time",
    "contacts": "can read everyone in your address book",
    "location_precise": "can place you to within a few metres",
}

UNCERTAIN_PURPOSE = "Its purpose is uncertain, so whether this is necessary could not be confirmed."

PURPOSE_NAMES = {
    "government": "government service",
    "news": "news site",
    "search": "search engine",
    "social": "social network",
    "recipe": "recipe site",
    "gaming": "game",
    "weather": "weather service",
    "image_tool": "image tool",
    "file_converter": "file converter",
    "free_download": "free download",
    "wallpaper_utility": "wallpaper app",
    "saas_b2b": "business tool",
    "maps_navigation": "maps app",
    "video_conference": "video call service",
    "healthcare_provider": "healthcare provider",
    "finance_investing": "investment service",
    "shopping_comparison": "price comparison site",
    "screen_recorder": "screen recorder",
    "password_manager": "password manager",
    "developer_tool": "developer tool",
    "accessibility_tool": "accessibility tool",
    "job_board": "job board",
    "ride_hailing": "ride-hailing service",
    "food_delivery": "food delivery service",
    "travel_booking": "travel booking site",
    "music_streaming": "music service",
    "video_streaming": "video service",
    "cloud_storage": "file sharing service",
    "legal_services": "legal service",
}


def category_label(value: str) -> str:
    return LABELS.get(value, value.replace(".", " ").replace("_", " ").capitalize())


def purpose_label(purpose: str) -> str:
    return PURPOSE_NAMES.get(purpose, purpose.replace("_", " "))


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _requester_name(event: PrivacyEvent) -> str:
    requester = event.requester
    if requester.display_name and requester.display_name != "Unknown requester":
        return requester.display_name
    return requester.origin or "This service"


def _sentence_list(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _rows(
    assessments: list[NecessityAssessment], explain_consequences: bool
) -> list[DecisionFinding]:
    """One row per category, warning on the ones that do not earn their place."""
    rows: list[DecisionFinding] = []
    for item in assessments:
        label = category_label(item.category.value)
        unnecessary = item.verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}
        consequence = CONSEQUENCES.get(item.category.value, "")
        if unnecessary:
            # A broad-access warning is only meaningful with its consequence spelled out.
            label = f"{label} — {consequence}" if explain_consequences and consequence else label
            severity: Literal["warn", "ok", "info"] = "warn"
        elif item.verdict == Necessity.REQUIRED:
            label = f"{label} — needed for this"
            severity = "ok"
        else:
            # Plausible but not required: a neutral note, never a green tick of approval.
            severity = "info"
        rows.append(DecisionFinding(label=label, severity=severity))
    return _ordered(rows, assessments)


def _ordered(
    rows: list[DecisionFinding], assessments: list[NecessityAssessment]
) -> list[DecisionFinding]:
    """Warnings first, most sensitive first within each group, so the eye lands on the worst."""
    from privacy_guardian.engine.classifier import load_sensitivities

    table = load_sensitivities()
    weight = {
        id(row): table.get(item.category.value, 0.0)
        for row, item in zip(rows, assessments, strict=False)
    }
    rank = {"warn": 0, "info": 1, "ok": 2}
    return sorted(
        rows,
        key=lambda row: (rank.get(row.severity, 1), -weight.get(id(row), 0.0), row.label),
    )


def _headline(
    event: PrivacyEvent,
    assessments: list[NecessityAssessment],
    profile: SiteOrAppProfile,
) -> tuple[str, str]:
    """The bold line and the paragraph under it, written for the moment of the decision."""
    who = _requester_name(event)
    purpose = purpose_label(event.requester.purpose)
    certain = event.requester.purpose != "unknown" and event.requester.purpose_confidence >= 0.35
    unnecessary = [
        category_label(item.category.value)
        for item in assessments
        if item.verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}
    ]
    sensitive = [
        item
        for item in assessments
        if item.category.value.split(".")[0]
        in {"government_id", "medical", "financial", "credentials", "biometric_photo"}
    ]

    if isinstance(event, FileUploadEvent):
        if sensitive:
            headline = "This file contains highly sensitive identity information."
        elif unnecessary:
            headline = "This file contains more than this site needs."
        else:
            headline = f"This file is being shared with {who}."
        body = (
            f"{_article(purpose).capitalize()} {purpose} does not appear to require most of "
            "this information."
            if certain and unnecessary
            else f"{who} has not made clear why it needs this information."
            if unnecessary
            else f"Nothing in this file looks out of place for {_article(purpose)} {purpose}."
            if certain
            else f"{who} has not made its purpose clear, so necessity could not be confirmed."
        )
        return headline, body

    if isinstance(event, FormObservedEvent):
        headline = (
            f"This form is asking for more than {_article(purpose)} {purpose} needs."
            if certain and unnecessary
            else "This form is asking for information it may not need."
            if unnecessary
            else f"{who} is asking for your details."
        )
        body = (
            f"The fields below are not needed to complete {_article(purpose)} {purpose}."
            if certain and unnecessary
            else "The fields below do not appear necessary for what you are doing."
            if unnecessary
            else f"Nothing here looks unusual for {who}."
        )
        return headline, body

    if isinstance(event, ConsentBannerEvent):
        headline = "This website wants to do more than store necessary cookies."
        body = (
            "Rejecting is hidden behind extra screens. Privacy Guardian can reject the "
            "optional cookies for you."
            if event.dark_patterns
            else "Privacy Guardian can reject the optional cookies for you."
        )
        return headline, body

    if isinstance(event, TrackingEvent):
        headline = f"{who} is building an advertising profile."
        body = (
            "Identifiers on this page can link what you do here to what you do on other websites."
        )
        return headline, body

    if isinstance(event, PolicyDocumentEvent):
        kind = "terms" if event.kind == "terms" else "privacy policy"
        if profile.clauses:
            headline = f"Before you accept these {kind}."
            body = "These clauses change what happens to your information after you agree."
        elif event.missing or profile.policy_missing:
            headline = f"{who} does not publish {_article(kind)} {kind}."
            body = "Collection, sharing and retention terms could not be checked."
        else:
            headline = f"Nothing unusual in these {kind}."
            body = f"{who} states the ordinary terms for this kind of service."
        return headline, body

    if isinstance(event, ClipboardReadEvent):
        headline = f"{who} just read your clipboard."
        kinds = [
            f"{_article(category_label(item.category.value))} "
            f"{category_label(item.category.value).lower()}"
            for item in assessments
        ]
        body = (
            f"Your clipboard currently contains what looks like {_sentence_list(kinds)}. "
            f"{who} does not need it for anything you are doing."
            if kinds
            else f"{who} read the clipboard in the background."
        )
        return headline, body

    if isinstance(event, ScreenCaptureEvent):
        headline = f"{who} can record your screen."
        body = "Everything visible on your display can be captured while this is active."
        return headline, body

    if isinstance(event, SystemAccessEvent):
        headline = (
            f"{who} already has broad access to your computer."
            if event.existing
            else f"{who} is requesting broad access to your computer."
        )
        body = (
            f"These permissions appear broader than necessary for {_article(purpose)} {purpose}."
            if certain
            else f"These permissions appear broader than {who} appears to need."
        )
        return headline, body

    if isinstance(event, PermissionRequestEvent):
        permission = category_label(
            event.permission if event.permission in LABELS else event.permission
        ).lower()
        # A grant made months ago is not a question being put to the person now, and
        # wording it as one is the difference between a report and a false alarm.
        headline = (
            f"{who} already has access to your {permission}."
            if event.existing
            else f"{who} was given access to your {permission}."
            if event.state == "granted"
            else f"{who} is using your {permission}."
            if event.state == "active"
            else f"{who} is asking for your {permission}."
        )
        body = (
            f"{_article(purpose).capitalize()} {purpose} does not normally need this."
            if certain and unnecessary
            else f"{who} has not explained why it needs this."
        )
        return headline, body

    labels = _sentence_list([category_label(item.category.value).lower() for item in assessments])
    headline = f"{who} is requesting {labels or 'access to your information'}."
    body = (
        f"This does not appear necessary for {_article(purpose)} {purpose}."
        if certain and unnecessary
        else f"{who} has not made clear why it needs this."
    )
    return headline, body


def _consequences(profile: SiteOrAppProfile) -> list[str]:
    effects = []
    if profile.retention == "after_deletion":
        effects.append("data may be kept after account deletion")
    if set(profile.shares_with) & {"advertising_partners", "data_brokers"}:
        effects.append("data may be shared with advertisers or data brokers")
    if profile.training_on_user_content:
        effects.append("content may be used for AI training")
    if profile.data_sale:
        effects.append("data may be sold")
    return effects


def _informational(
    event: PrivacyEvent, assessments: list[NecessityAssessment]
) -> tuple[str, str] | None:
    """An expected request is reported as a fact, not questioned."""
    who = _requester_name(event)
    purpose = purpose_label(event.requester.purpose)
    certain = event.requester.purpose != "unknown" and event.requester.purpose_confidence >= 0.35
    if not certain or any(
        item.verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG} for item in assessments
    ):
        return None
    encrypted = event.requester.origin.startswith("https://")
    if isinstance(event, FileUploadEvent):
        kinds = {item.category.value.split(".")[0] for item in assessments}
        what = (
            "Identity document"
            if "government_id" in kinds or "biometric_photo" in kinds
            else "Financial document"
            if "financial" in kinds
            else "File"
        )
        body = (
            f"Expected for {_article(purpose)} {purpose}."
            if certain
            else f"Nothing in it looks out of place for {who}."
        )
        if encrypted:
            body += " Sent over an encrypted connection."
        return f"{what} shared with {who}", body
    if assessments:
        labels = _sentence_list(
            [category_label(item.category.value).lower() for item in assessments[:3]]
        )
        body = (
            f"Expected for {_article(purpose)} {purpose}."
            if certain
            else f"{who} has not explained why, but nothing here looks unusual."
        )
        return f"{labels.capitalize()} shared with {who}", body
    return None


def explain(
    event: PrivacyEvent,
    assessments: list[NecessityAssessment],
    profile: SiteOrAppProfile,
    notes: list[str] | None = None,
    informational: bool = False,
) -> tuple[str, str, list[DecisionFinding], list[str]]:
    """Return the widget's headline, body, finding rows and 'why am I seeing this' detail."""
    headline, body = (informational and _informational(event, assessments)) or _headline(
        event, assessments, profile
    )
    if event.requester.purpose == "unknown" or event.requester.purpose_confidence < 0.35:
        # Say plainly that necessity could not be judged rather than implying it was.
        body = UNCERTAIN_PURPOSE if not body or informational else body + " " + UNCERTAIN_PURPOSE
    findings = _rows(
        assessments,
        explain_consequences=isinstance(event, SystemAccessEvent | PermissionRequestEvent),
    )
    effects = _consequences(profile)
    rationale = [item.rationale for item in assessments]
    rationale.extend(notes or [])
    if effects:
        rationale.append("The policy says " + "; ".join(effects) + ".")
    return headline, body, findings, rationale


def summarize(headline: str, body: str) -> str:
    """The single-line form kept in history, logs and accessibility labels."""
    return f"{headline} {body}".strip()


def consent_findings(event: ConsentBannerEvent) -> list[DecisionFinding]:
    """Cookie purposes, read back as what they actually do."""
    rows = [DecisionFinding(label="Store necessary cookies", severity="ok")]
    wording = {
        "analytics": "Track your activity for analytics",
        "advertising": "Build an advertising profile about you",
        "personalisation": "Remember choices to personalise what you see",
        "social": "Share your activity with social networks",
        "functional": "Remember preferences for this site",
    }
    for purpose in event.purposes:
        if purpose == "necessary":
            continue
        rows.append(
            DecisionFinding(
                label=wording.get(purpose, purpose.replace("_", " ").capitalize()), severity="warn"
            )
        )
    if event.vendor_count:
        rows.insert(
            1,
            DecisionFinding(
                label=f"Share identifiers with {event.vendor_count} advertising partners",
                severity="warn",
            ),
        )
    return [row for row in rows if row.severity == "warn"] + [
        row for row in rows if row.severity == "ok"
    ]


def form_findings(
    event: FormObservedEvent, unnecessary: set[DataCategory]
) -> list[DecisionFinding]:
    """One row per field the form asks for, named the way the form names it."""
    rows: list[DecisionFinding] = []
    seen: set[str] = set()
    for field in event.fields:
        if field.category is None:
            continue
        label = category_label(field.category.value)
        if label in seen:
            continue
        seen.add(label)
        if field.category in unnecessary:
            rows.append(DecisionFinding(label=label, severity="warn"))
        else:
            rows.append(DecisionFinding(label=f"{label} — needed for this", severity="ok"))
    return [row for row in rows if row.severity == "warn"] + [
        row for row in rows if row.severity == "ok"
    ]
