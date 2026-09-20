from __future__ import annotations

from privacy_guardian.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    Decision,
    DecisionFinding,
    FileUploadEvent,
    FormObservedEvent,
    Outcome,
    PermissionRequestEvent,
    PolicyDocumentEvent,
    PrivacyEvent,
    SystemAccessEvent,
    TrackingEvent,
)

# The point past which an intervention is shown in the strongest register: a solid red
# band that pulses when it arrives. Identity documents, passwords and broad desktop
# access all score here; a consent banner with a buried reject button does not.
ACT_NOW_RISK = 0.75
# Below this an informational card is reporting that things are fine.
SETTLED_RISK = 0.25


def urgency_for(decision: Decision) -> str:
    """Which register the widget speaks in, from the verdict and the risk.

    The tiers map onto colours people already know: two reds for the cards that hold
    something up (deep and solid for the worst of them), amber for a warning that
    asks nothing, green for fine or already handled, blue for a plain note.
    """
    if decision.outcome == Outcome.INTERVENE:
        return "act_now" if decision.risk >= ACT_NOW_RISK else "attention"
    if decision.auto_action:
        # The person authorised this; the card reports that it was done for them.
        return "all_clear"
    if any(finding.severity == "warn" for finding in decision.findings):
        return "heads_up"
    if decision.risk < SETTLED_RISK:
        return "all_clear"
    return "heads_up" if decision.outcome == Outcome.INFORM else "note"


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
    "tracking": {"learn_more": "Learn more", "block": "Block if possible", "continue": "Not now"},
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
# "Cross origin storage identifier" tells the reader nothing they can act on. These
# belong under "Why am I seeing this?": on the card itself they were five rows that
# all say some version of "they can follow you", which is the row above them.
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
# Already said by the rows: the tracker list and the fingerprinting row.
COVERED_SIGNALS = frozenset({"known_tracker_requests", "fingerprinting"})
# Every one of these is a way of doing the same thing — handing this visit to other
# companies — so they are one row, not one row each.
FOLLOWING_SIGNALS = frozenset(
    {
        "known_tracker_requests",
        "tracking_pixels",
        "url_decoration",
        "url_identifier",
        "cross_origin_storage_identifier",
        "cross_site_identifier",
        "cname_cloaking",
        "persistent_third_party_cookies",
        "persistent_cookie",
    }
)


def named_hosts(hosts: list[str], limit: int = 3) -> str:
    """Name a few and count the rest: enough to recognise, not a wall of hosts."""
    shown = ", ".join(hosts[:limit])
    return f"{shown} and {len(hosts) - limit} more" if len(hosts) > limit else shown


def tracking_rows(event: TrackingEvent) -> list[DecisionFinding]:
    """The three things tracking actually does to the person, not the nine ways it does them.

    A page carries pixels, tagged links, a stored identifier and a cloaked subdomain;
    naming each one filled the card with mechanisms and left the reader to work out
    that they add up to one sentence. They are folded into that sentence here, and the
    mechanisms are listed under "Why am I seeing this?" for anyone who wants them.
    """
    rows: list[DecisionFinding] = []
    companies = sorted(set(event.tracker_domains))
    signals = set(event.signals)
    if companies:
        rows.append(
            DecisionFinding(
                label=f"Shares what you do here with {len(companies)} other "
                f"{'company' if len(companies) == 1 else 'companies'}",
                severity="warn",
                detail=named_hosts(companies),
            )
        )
    elif signals & FOLLOWING_SIGNALS:
        rows.append(
            DecisionFinding(
                label="Carries an identifier that follows you to other websites",
                severity="warn",
            )
        )
    if event.fingerprinting:
        rows.append(
            DecisionFinding(
                label="Recognises this device even after you clear cookies", severity="warn"
            )
        )
    if "identity_linking" in signals:
        rows.append(
            DecisionFinding(label="Can match this browsing to your email address", severity="warn")
        )
    return rows


def tracking_mechanisms(event: TrackingEvent) -> list[str]:
    """The mechanism-by-mechanism detail, for the reasoning panel rather than the card."""
    lines: list[str] = []
    for signal in event.signals:
        name = str(signal)
        if name in COVERED_SIGNALS or name == "identity_linking":
            continue
        prefix, _, suffix = name.partition(":")
        wording = SIGNAL_WORDING.get(prefix)
        line = (
            f"{wording} {suffix}"
            if wording and suffix
            else wording or name.replace("_", " ").capitalize()
        )
        lines.append(line if line.endswith(".") else line + ".")
    return lines


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
    # Four clauses is already a lot to take in standing at a checkout; the complete
    # list is one line down under "Why am I seeing this?".
    warnings = [row for row in rows if row.severity == "warn"]
    if len(warnings) > 4:
        return [
            *warnings[:4],
            DecisionFinding(
                label=f"{len(warnings) - 4} more worth reading before you agree", severity="warn"
            ),
        ]
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
    decision.urgency = urgency_for(decision)  # type: ignore[assignment]
    return decision
