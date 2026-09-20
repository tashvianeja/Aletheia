from __future__ import annotations

from typing import Literal

from privacy_guardian.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    DecisionFinding,
    FileUploadEvent,
    Finding,
    FormObservedEvent,
    PermissionRequestEvent,
    PolicyDocumentEvent,
    PrivacyEvent,
    RedactedDocumentEvent,
    ScreenCaptureEvent,
    SystemAccessEvent,
    TrackingEvent,
)
from privacy_guardian.engine.context import SiteOrAppProfile
from privacy_guardian.engine.labels import (
    LABELS,
    category_label,
    lowered,
    plural_label,
    purpose_label,
)
from privacy_guardian.engine.labels import article as _article
from privacy_guardian.engine.necessity import Necessity, NecessityAssessment

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


def form_task(event: FormObservedEvent) -> str:
    """What this form is for, phrased to sit after "needed to"."""
    from privacy_guardian.intelligence.intent import classify_form
    from privacy_guardian.intelligence.necessity import INTENT_PHRASES, MIN_INTENT_CONFIDENCE

    result = classify_form(event.fields, event.context, event.requester.purpose)
    if result.confidence < MIN_INTENT_CONFIDENCE:
        return ""
    return INTENT_PHRASES.get(result.intent, "")


UNCERTAIN_PURPOSE = "Its purpose is uncertain, so whether this is necessary could not be confirmed."


def _requester_name(event: PrivacyEvent) -> str:
    requester = event.requester
    if requester.display_name and requester.display_name != "Unknown requester":
        return requester.display_name
    return requester.origin or "This service"


def _sentence_list(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def evidence(findings: list[Finding] | None) -> dict[DataCategory, str]:
    """Where each thing was found, so a row is checkable rather than just asserted.

    Page numbers only earn their place in a document that has more than one, and
    metadata always does: that a holiday photo carries the spot it was taken is the
    whole point of saying so.
    """
    pages: dict[DataCategory, set[int]] = {}
    metadata: set[DataCategory] = set()
    for finding in findings or []:
        if finding.span_ref == "metadata":
            metadata.add(finding.category)
        elif finding.page:
            pages.setdefault(finding.category, set()).add(finding.page)
    multipage = len({page for found in pages.values() for page in found}) > 1
    details: dict[DataCategory, str] = {}
    for category in {*pages, *metadata}:
        parts: list[str] = []
        found = sorted(pages.get(category, ()))
        if found and multipage:
            shown = ", ".join(str(page) for page in found[:3])
            more = f" and {len(found) - 3} more" if len(found) > 3 else ""
            parts.append(f"Page{'s' if len(found) > 1 else ''} {shown}{more}")
        if category in metadata:
            parts.append("Recorded in the file's own metadata")
        if parts:
            details[category] = " · ".join(parts)
    return details


def _rows(
    assessments: list[NecessityAssessment],
    explain_consequences: bool,
    details: dict[DataCategory, str] | None = None,
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
        rows.append(
            DecisionFinding(
                label=label, severity=severity, detail=(details or {}).get(item.category, "")
            )
        )
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
    flagged: set[DataCategory] | None = None,
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
        needless = lowered(unnecessary[0]) if len(unnecessary) == 1 else "most of this information"
        body = (
            f"{_article(purpose).capitalize()} {purpose} does not appear to require {needless}."
            if certain and unnecessary
            else f"{who} has not made clear why it needs this information."
            if unnecessary
            else f"Nothing in this file looks out of place for {_article(purpose)} {purpose}."
            if certain
            else f"{who} has not made its purpose clear, so necessity could not be confirmed."
        )
        return headline, body

    if isinstance(event, FormObservedEvent):
        # Name the task, not the industry. "More than a recipe site needs" is not what a
        # reader is doing; "more than it needs to join a mailing list" is.
        task = form_task(event)
        # And say it only about what the card is actually going to show. A full name on
        # a survey is not worth a row, so it is not worth a headline either: announcing
        # over-collection and then listing nothing is the card arguing with itself.
        raised = (
            [category_label(category.value) for category in flagged]
            if flagged is not None
            else unnecessary
        )
        headline = (
            f"This form is asking for more than it needs to {task}."
            if task and raised
            else f"This form is asking for more than {_article(purpose)} {purpose} needs."
            if certain and raised
            else "This form is asking for information it may not need."
            if raised
            else f"{who} is asking for your details."
        )
        body = "" if raised else f"Nothing here looks unusual for {who}."
        return headline, body

    if isinstance(event, ConsentBannerEvent):
        headline = f"{who} wants more than the cookies it needs."
        # "Privacy Guardian can reject the optional cookies for you" is what the
        # Reject optional button says; the body only speaks when it knows something
        # the headline, the rows and the buttons do not.
        body = "Rejecting is hidden behind extra screens." if event.dark_patterns else ""
        return headline, body

    if isinstance(event, TrackingEvent):
        return f"{who} is building an advertising profile.", ""

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
            f"{lowered(category_label(item.category.value))}"
            for item in assessments
        ]
        body = (
            f"Your clipboard currently contains what looks like {_sentence_list(kinds)}. "
            f"{who} does not need it for anything you are doing."
            if kinds
            else f"{who} read the clipboard in the background."
        )
        return headline, body

    if isinstance(event, RedactedDocumentEvent):
        count = event.marks
        boxes = "one redaction box" if count == 1 else f"{count} redaction boxes"
        headline = f"{event.filename or 'This file'} has {boxes} drawn by Privacy Guardian."
        body = (
            "The details are covered, not removed, so a copy with the boxes taken off can "
            "be made beside it. Everything else in the file, including any compression, stays "
            "as it is. Nothing leaves this device."
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

    labels = _sentence_list([lowered(category_label(item.category.value)) for item in assessments])
    headline = f"{who} is requesting {labels or 'access to your information'}."
    body = (
        f"This does not appear necessary for {_article(purpose)} {purpose}."
        if certain and unnecessary
        else f"{who} has not made clear why it needs this."
    )
    return headline, body


# Singular and plural for each verdict, so several categories that share a verdict
# become one sentence instead of the same sentence repeated with a different noun.
_VERDICT_WORDING: dict[Necessity, tuple[str, str]] = {
    Necessity.RED_FLAG: (
        "is unusually sensitive and does not appear necessary",
        "are unusually sensitive and do not appear necessary",
    ),
    Necessity.UNNECESSARY: ("does not appear necessary", "do not appear necessary"),
    Necessity.REASONABLE: ("may reasonably be used", "may reasonably be used"),
    Necessity.REQUIRED: ("is needed", "are needed"),
}


def _necessity_notes(event: PrivacyEvent, assessments: list[NecessityAssessment]) -> list[str]:
    """The "why am I seeing this" reasoning, grouped so it can be read at a glance."""
    if isinstance(event, FormObservedEvent) and form_task(event):
        # A form was judged on what it is for, and the judgement already wrote itself a
        # sentence naming that task. Restating it against the site's industry instead
        # answers a question nobody asked: the reader is filling in this form.
        return [
            item.rationale
            for item in assessments
            if item.rationale and item.verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}
        ]
    certain = event.requester.purpose != "unknown" and event.requester.purpose_confidence >= 0.35
    if not assessments or not certain:
        # The body already says the purpose could not be established; saying it once
        # more per category is how four fields became four identical sentences.
        return []
    named = purpose_label(event.requester.purpose)
    notes: list[str] = []
    for verdict, (singular, plural) in _VERDICT_WORDING.items():
        matching = [item for item in assessments if item.verdict == verdict]
        if not matching:
            continue
        labels = [category_label(item.category.value) for item in matching]
        # One plural label still takes the plural verb: "Persistent device identifiers
        # does not appear necessary" was the sentence this produced.
        verb = plural if len(labels) > 1 or plural_label(matching[0].category.value) else singular
        named_list = _sentence_list([labels[0], *(lowered(label) for label in labels[1:])])
        notes.append(f"{named_list} {verb} for {_article(named)} {named}.")
    return notes


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
        if not encrypted:
            body += " This connection is not encrypted."
        return f"{what} shared with {who}", body
    if assessments:
        named = [category_label(item.category.value) for item in assessments[:3]]
        labels = _sentence_list([named[0], *(lowered(label) for label in named[1:])])
        body = (
            f"Expected for {_article(purpose)} {purpose}."
            if certain
            else f"{who} has not explained why, but nothing here looks unusual."
        )
        return f"{labels} shared with {who}", body
    return None


def explain(
    event: PrivacyEvent,
    assessments: list[NecessityAssessment],
    profile: SiteOrAppProfile,
    notes: list[str] | None = None,
    informational: bool = False,
    found: list[Finding] | None = None,
    flagged: set[DataCategory] | None = None,
) -> tuple[str, str, list[DecisionFinding], list[str]]:
    """Return the widget's headline, body, finding rows and 'why am I seeing this' detail."""
    from privacy_guardian.engine.presentation import tracking_mechanisms

    headline, body = (informational and _informational(event, assessments)) or _headline(
        event, assessments, profile, flagged
    )
    # Whether a request was necessary is the question a form or an upload is judged on.
    # A page that is tracking you, a cookie banner and a policy are not judged on it,
    # and the caveat only made those cards longer without answering anything they ask.
    # An offer to restore a file we redacted is not a request at all, so it is not judged either.
    judged_on_necessity = not isinstance(
        event, TrackingEvent | ConsentBannerEvent | PolicyDocumentEvent | RedactedDocumentEvent
    )
    uncertain = event.requester.purpose == "unknown" or event.requester.purpose_confidence < 0.35
    # A form is judged on what it is for, not on what the site sells. Where its own
    # intent is known, "its purpose is uncertain" contradicts the headline directly
    # above it, which has just named the task in so many words.
    if isinstance(event, FormObservedEvent) and form_task(event):
        uncertain = False
    if uncertain and judged_on_necessity:
        # Say plainly that necessity could not be judged rather than implying it was.
        body = UNCERTAIN_PURPOSE if not body or informational else body + " " + UNCERTAIN_PURPOSE
    rows = _rows(
        assessments,
        explain_consequences=isinstance(event, SystemAccessEvent | PermissionRequestEvent),
        details=evidence(found),
    )
    effects = _consequences(profile)
    rationale = _necessity_notes(event, assessments)
    if uncertain and not judged_on_necessity:
        rationale.append(UNCERTAIN_PURPOSE)
    # The mechanism-by-mechanism detail the card no longer carries: still here, one
    # click away, for anyone who wants to know how it is being done.
    if isinstance(event, TrackingEvent):
        rationale.extend(tracking_mechanisms(event))
    if isinstance(event, ConsentBannerEvent):
        rationale.extend(consent_meanings(event))
    rationale.extend(notes or [])
    if effects:
        rationale.append("The policy says " + "; ".join(effects) + ".")
    return headline, body, rows, rationale


def summarize(headline: str, body: str) -> str:
    """The single-line form kept in history, logs and accessibility labels."""
    return f"{headline} {body}".strip()


# What each optional purpose is for, in the reader's terms.
CONSENT_PURPOSES = {
    "analytics": "analytics",
    "advertising": "advertising",
    "personalisation": "personalisation",
    "social": "social media",
    "functional": "remembering preferences",
}
# The full sentence for each, kept for the reasoning panel.
CONSENT_MEANING = {
    "analytics": "Analytics cookies track what you do on this site.",
    "advertising": "Advertising cookies build a profile about you.",
    "personalisation": "Personalisation cookies remember choices to change what you see.",
    "social": "Social cookies share your activity with social networks.",
    "functional": "Functional cookies remember your preferences for this site.",
}


def consent_findings(event: ConsentBannerEvent) -> list[DecisionFinding]:
    """One row for what the banner wants, one for who else gets it.

    Four purposes were four rows, and the row saying necessary cookies are stored was
    a fifth telling the reader about the part nobody objects to. It is one choice —
    accept or reject the optional ones — so it reads as one line.
    """
    optional = [
        CONSENT_PURPOSES.get(purpose, purpose.replace("_", " "))
        for purpose in dict.fromkeys(event.purposes)
        if purpose != "necessary"
    ]
    rows: list[DecisionFinding] = []
    if optional:
        named = (
            [*optional[:3], f"{len(optional) - 3} more"] if len(optional) > 3 else list(optional)
        )
        rows.append(
            DecisionFinding(label=f"Wants cookies for {_sentence_list(named)}", severity="warn")
        )
    if event.vendor_count:
        rows.append(
            DecisionFinding(
                label=f"Shares what it learns with {event.vendor_count} other companies",
                severity="warn",
            )
        )
    return rows


def consent_meanings(event: ConsentBannerEvent) -> list[str]:
    """What each optional purpose actually does, for the reasoning panel."""
    return [
        CONSENT_MEANING[purpose]
        for purpose in dict.fromkeys(event.purposes)
        if purpose in CONSENT_MEANING
    ]


def form_findings(
    event: FormObservedEvent,
    flagged: set[DataCategory],
    unnecessary: set[DataCategory] | None = None,
) -> list[DecisionFinding]:
    """The fields worth looking at, named the way the form names them.

    Where something needs looking at, the fields that are fine are not what the person
    is being asked about, and listing them doubled the height of the card. They are
    only listed when they are the whole answer: nothing here needs looking at.

    `flagged` is what the card is warning about; `unnecessary` is the wider set the
    engine could not justify. A full name on a survey is in the second and not the
    first, and putting a warning triangle beside it sits it next to the password and
    says the two are the same size of problem.
    """
    unnecessary = flagged if unnecessary is None else unnecessary
    warnings: list[DecisionFinding] = []
    fine: list[DecisionFinding] = []
    seen: set[str] = set()
    for field in event.fields:
        if field.category is None:
            continue
        label = category_label(field.category.value)
        if label in seen:
            continue
        seen.add(label)
        if field.category in flagged:
            warnings.append(DecisionFinding(label=label, severity="warn"))
        elif field.category in unnecessary:
            # Asked for, not obviously needed, not worth a warning: a neutral note, and
            # never a tick claiming this form needs it.
            fine.append(DecisionFinding(label=label, severity="info"))
        else:
            fine.append(DecisionFinding(label=f"{label} — needed for this", severity="ok"))
    if not warnings:
        return fine
    if len(warnings) > 4:
        return [
            *warnings[:4],
            DecisionFinding(label=f"and {len(warnings) - 4} more", severity="warn"),
        ]
    return warnings
