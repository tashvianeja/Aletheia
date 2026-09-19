from __future__ import annotations

from privacy_guardian.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    Decision,
    DecisionFinding,
    FileUploadEvent,
    FormObservedEvent,
    PermissionRequestEvent,
    PolicyDocumentEvent,
    PrivacyEvent,
    SystemAccessEvent,
    TrackingEvent,
)

# What each button says at the moment it is shown. The same action id reads differently
# depending on what the user is in the middle of doing, exactly as the mockups show.
ACTION_LABELS: dict[str, dict[str, str]] = {
    "file_upload": {
        "cancel": "Cancel",
        "continue": "Upload anyway",
        "redact": "Create redacted copy",
        "strip_metadata": "Remove location first",
    },
    "form_observed": {"continue": "Continue", "review_fields": "Review fields"},
    "form_submit": {
        "cancel": "Don't send",
        "continue": "Continue",
        "review_fields": "Review fields",
    },
    "consent_banner": {
        "continue": "Accept",
        "view_details": "View details",
        "reject_optional": "Reject optional",
    },
    "tracking": {"learn_more": "Learn more", "block": "Block if possible"},
    "policy_document": {
        "cancel": "Don't accept",
        "continue": "Continue",
        "view_details": "Show me where",
    },
    "clipboard_read": {
        "continue": "Allow this time",
        "open_settings": "Privacy settings",
        "clear_clipboard": "Clear clipboard",
    },
    "permission_request": {
        "mark_expected": "Expected",
        "open_settings": "Review access",
        "continue": "Not now",
    },
    "system_access": {
        "mark_expected": "Expected",
        "open_settings": "Review access",
        "continue": "Not now",
    },
    "screen_capture": {
        "mark_expected": "Expected",
        "open_settings": "Review access",
        "continue": "Not now",
    },
    "startup_registration": {
        "mark_expected": "Expected",
        "open_settings": "Review access",
        "continue": "Not now",
    },
}

# The safe option is the easy one: a remedy that still lets the user finish the task beats
# a plain refusal, and a refusal beats carrying on.
REMEDY_ORDER = (
    "redact",
    "strip_metadata",
    "review_fields",
    "reject_optional",
    "clear_clipboard",
    "block",
    "view_details",
    "open_settings",
    "cancel",
)
# The "do it anyway" escape hatch, rendered as plain text away from the real buttons.
ESCAPES = ("continue", "mark_expected", "learn_more")


def action_labels(event_type: str, actions: list[str]) -> dict[str, str]:
    table = ACTION_LABELS.get(event_type, {})
    return {action: table[action] for action in actions if action in table}


def action_tiers(event_type: str, actions: list[str]) -> tuple[str, str]:
    """Pick the filled button and the plain-text escape from the available actions."""
    primary = next((action for action in REMEDY_ORDER if action in actions), "")
    escapes = [action for action in ESCAPES if action in actions and action != primary]
    # Two escapes (tracking offers only "Learn more") would leave no ordinary button.
    tertiary = escapes[0] if escapes and len(actions) > 2 else ""
    if not tertiary and "continue" in actions and actions != [primary, "continue"]:
        tertiary = "continue"
    return primary, tertiary


def context_line(event: PrivacyEvent, filename: str = "") -> tuple[str, str]:
    """The 'passport.pdf -> shrinkpix.example' line above the buttons."""
    destination = event.requester.display_name or event.requester.origin
    subjects = {
        "file_upload": filename or "File upload",
        "form_observed": "Form on this page",
        "form_submit": "Form on this page",
        "consent_banner": "Consent banner",
        "policy_document": "Terms" if getattr(event, "kind", "") == "terms" else "Privacy policy",
        "tracking": "This page",
        "clipboard_read": "Clipboard",
    }
    subject = subjects.get(event.event_type, "")
    if not subject or event.requester.kind != "website":
        return "", ""
    return subject, destination


def layout_for(event: PrivacyEvent) -> str:
    """Broad-access warnings lead with the list; everything else leads with the sentence."""
    return (
        "findings_first"
        if isinstance(event, SystemAccessEvent | PermissionRequestEvent)
        else "body_first"
    )


def findings_for(
    event: PrivacyEvent,
    default: list[DecisionFinding],
    unnecessary: set[DataCategory],
) -> list[DecisionFinding]:
    """Event-specific rows where the raw categories would not say enough."""
    from privacy_guardian.engine.explain import consent_findings, form_findings

    if isinstance(event, ConsentBannerEvent):
        return consent_findings(event)
    if isinstance(event, FormObservedEvent):
        rows = form_findings(event, {c for c in event.data_categories if c in unnecessary})
        return rows or default
    if isinstance(event, TrackingEvent):
        return tracking_rows(event) or default
    if isinstance(event, PolicyDocumentEvent):
        return default
    if isinstance(event, ClipboardReadEvent):
        from privacy_guardian.engine.labels import article, category_label, lowered

        when = event.ts.astimezone().strftime("%H:%M:%S")
        who = event.requester.display_name or event.requester.key
        rows = [DecisionFinding(label=f"Clipboard read at {when} by {who}", severity="warn")]
        rows.extend(
            DecisionFinding(
                label="Content looks like "
                f"{article(category_label(category.value))} "
                f"{lowered(category_label(category.value))}",
                severity="warn",
            )
            for category in event.data_categories
        )
        return rows
    if isinstance(event, FileUploadEvent):
        return default
    return default


# What each tracking mechanism does, in place of the detector's own name for it.
# "Cross origin storage identifier" tells the reader nothing they can act on.
SIGNAL_WORDING = {
    "persistent_third_party_cookies": "Stores third-party cookies that outlast this visit",
    "url_decoration": "Tags the links you follow with an identifier for you",
    "cross_origin_storage_identifier": "Reuses one stored identifier across separate websites",
    "cname_cloaking": "Disguises a tracker as part of this website",
    "tracking_pixels": "Loads invisible images that report which pages you open",
    "identity_linking": "Sends a scrambled form of your identity to match you elsewhere",
    "persistent_cookie": "Sets an identifier that lasts",
    "cross_site_identifier": "Reuses one identifier across separate websites",
    "url_identifier": "Carries an identifier for you in page addresses",
}
# Already said by the rows above: the tracker list and the fingerprinting row.
COVERED_SIGNALS = frozenset({"known_tracker_requests", "fingerprinting"})


def named_hosts(hosts: list[str], limit: int = 3) -> str:
    """Name a few and count the rest: enough to recognise, not a wall of hosts."""
    shown = ", ".join(hosts[:limit])
    return f"{shown} and {len(hosts) - limit} more" if len(hosts) > limit else shown


def tracking_rows(event: TrackingEvent) -> list[DecisionFinding]:
    """Turn tracking mechanisms into what they mean for the person reading."""
    rows: list[DecisionFinding] = []
    domains = sorted(set(event.tracker_domains))
    if domains:
        rows.append(
            DecisionFinding(
                label=f"Links this visit to activity on {len(domains)} other website"
                f"{'s' if len(domains) != 1 else ''}",
                severity="warn",
                detail=named_hosts(domains),
            )
        )
    if event.fingerprinting:
        rows.append(
            DecisionFinding(
                label="Creates a fingerprint of this device",
                severity="warn",
                detail="Recognises this browser again even after you clear cookies",
            )
        )
    for signal in event.signals:
        text = str(signal)
        if text in COVERED_SIGNALS:
            continue
        prefix, _, suffix = text.partition(":")
        wording = SIGNAL_WORDING.get(prefix)
        label = (
            f"{wording} {suffix}"
            if wording and suffix
            else wording or text.replace("_", " ").capitalize()
        )
        rows.append(DecisionFinding(label=label, severity="warn"))
    return rows[:5]


def policy_rows(clauses: list[object], nothing_unusual: list[str]) -> list[DecisionFinding]:
    """Material clauses first, then the ordinary things that turned out fine."""
    wording = {
        "third_party_sharing": "Data may be shared with third parties",
        "training_on_user_content": "Your submitted content may be used to improve their services",
        "retention_after_deletion": "Account data may be kept after you delete your account",
        "arbitration": "Arbitration clause: disputes go to private arbitration, not court",
        "data_sale": "Data may be sold to other companies",
        "international_transfer": "Data may be moved to other countries",
        "advertising_partners": "Identifiers may be shared with advertising partners",
        "class_action_waiver": "You give up the right to join a class action",
        "unilateral_change": "Terms can be changed without telling you",
    }
    rows: list[DecisionFinding] = []
    for clause in clauses:
        name = clause.get("category", "") if isinstance(clause, dict) else str(clause)
        if not name:
            continue
        detail = str(clause.get("citation", "")) if isinstance(clause, dict) else ""
        rows.append(
            DecisionFinding(
                label=wording.get(name, name.replace("_", " ").capitalize()),
                severity="warn",
                detail=detail,
            )
        )
    rows.extend(
        DecisionFinding(label=str(item).replace("_", " ").capitalize(), severity="ok")
        for item in nothing_unusual
    )
    return rows


def decorate(decision: Decision, event: PrivacyEvent, filename: str = "") -> Decision:
    """Attach the presentation fields the widget needs, leaving the verdict untouched."""
    subject, destination = context_line(event, filename)
    decision.subject = subject
    decision.destination = destination
    decision.action_labels = action_labels(event.event_type, decision.actions)
    decision.primary_action, decision.tertiary_action = action_tiers(
        event.event_type, decision.actions
    )
    decision.layout = layout_for(event)  # type: ignore[assignment]
    return decision
