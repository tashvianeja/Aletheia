"""What a workflow says for itself once it has run.

Every action that does something on the person's behalf ends in a card that says what
was done, in the same words on the desktop and in the page. The words are composed
here, once, from the event the action answered and the result of carrying it out,
so the two surfaces cannot drift apart and neither has to know how the other works.
"""

from __future__ import annotations

from typing import Any

from aletheia.core.events import (
    ClipboardReadEvent,
    Decision,
    FormObservedEvent,
    PermissionRequestEvent,
    PrivacyEvent,
    SystemAccessEvent,
    TrackingEvent,
)
from aletheia.engine.labels import article, category_label, lowered, plural_label
from aletheia.util.i18n import tr

# The actions that end in a report. Carrying on and refusing do nothing that needs
# reporting, and the two that open the dashboard are their own report.
REPORTED = frozenset(
    {
        "redact",
        "unredact",
        "strip_metadata",
        "reject_optional",
        "block",
        "clear_fields",
        "redact_fields",
        "review_fields",
        "clear_clipboard",
        "open_settings",
        "mark_expected",
    }
)


def sentence_list(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def named(categories: list[Any]) -> list[str]:
    """Data categories as a reader would say them mid-sentence, each said once."""
    names = [lowered(category_label(str(category))) for category in categories if category]
    return list(dict.fromkeys(names))


def _things(categories: list[Any]) -> list[str]:
    """Categories as things: "a password", "persistent device identifiers"."""
    things: list[str] = []
    for category in categories:
        name = lowered(category_label(str(category)))
        things.append(name if plural_label(str(category)) else f"{article(name)} {name}")
    return list(dict.fromkeys(things))


def capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]


def _who(event: PrivacyEvent) -> str:
    requester = event.requester
    return requester.display_name or requester.origin or requester.key


def _access(event: PrivacyEvent) -> str:
    """The one permission a desktop notice is about, in words, or nothing."""
    if isinstance(event, PermissionRequestEvent) and event.permission:
        from aletheia.sensors.platform.base import PERMISSION_CATEGORIES

        category = PERMISSION_CATEGORIES.get(event.permission)
        return category_label(category.value) if category else event.permission
    if isinstance(event, SystemAccessEvent) and event.data_categories:
        return sentence_list([category_label(c.value) for c in event.data_categories])
    if event.data_categories:
        return sentence_list([category_label(c.value) for c in event.data_categories])
    return ""


def report_for(
    event: PrivacyEvent, decision: Decision, action: str, result: dict[str, Any]
) -> dict[str, Any] | None:
    """The card shown once `action` has been carried out for `event`, or None.

    `result` is what carrying it out produced: the redacted file's name, the ids of
    the fields that were blanked. The headline says what happened; the body says what
    it means for the person, and what it did not do.
    """
    if action not in REPORTED:
        return None
    who = _who(event)
    headline = body = ""
    if action == "redact":
        removed = named(event.data_categories)
        headline = tr("done_redact", filename=str(result.get("filename", "")))
        body = (
            tr("done_redact_body", removed=capitalised(sentence_list(removed)))
            if removed
            else tr("done_redact_body_plain")
        )
    elif action == "unredact":
        headline = tr("done_unredact", filename=str(result.get("filename", "")))
        body = tr("done_unredact_body", folder=str(result.get("folder", "")))
    elif action == "strip_metadata":
        headline = tr("done_strip", filename=str(result.get("filename", "")))
        body = tr("done_strip_body")
    elif action == "reject_optional":
        headline = tr("done_reject", site=who)
        body = tr("done_reject_remembered") if result.get("remembered") else tr("done_reject_body")
    elif action == "block":
        count = len(set(event.tracker_domains)) if isinstance(event, TrackingEvent) else 0
        headline = tr("done_block", site=who)
        body = (
            tr("done_block_body", count=count)
            if count > 1
            else tr("done_block_body_one")
            if count
            else tr("done_block_body_none")
        )
    elif action == "clear_fields":
        cleared = _field_names(event, list(result.get("fields", [])))
        count = len(result.get("fields", []))
        headline = tr("done_clear_fields", count=count) if count != 1 else tr("done_clear_field")
        body = (
            tr("done_clear_fields_body", names=capitalised(sentence_list(cleared)))
            if cleared
            else tr("done_clear_fields_body_plain")
        )
    elif action == "redact_fields":
        redacted = _field_names(event, list(result.get("fields", [])))
        count = len(result.get("fields", []))
        headline = tr("done_redact_fields", count=count) if count != 1 else tr("done_redact_field")
        body = (
            tr("done_redact_fields_body", names=capitalised(sentence_list(redacted)), site=who)
            if redacted
            else tr("done_redact_fields_body_plain", site=who)
        )
    elif action == "review_fields":
        count = len(result.get("fields", []))
        headline = tr("done_review", count=count) if count != 1 else tr("done_review_one")
        body = tr("done_review_body")
    elif action == "clear_clipboard":
        what = _things(event.data_categories) if isinstance(event, ClipboardReadEvent) else []
        headline = tr("done_clipboard")
        body = (
            tr("done_clipboard_body", what=sentence_list(what), app=who)
            if what
            else tr("done_clipboard_body_plain", app=who)
        )
    elif action == "open_settings":
        access = _access(event)
        headline = tr("done_settings")
        body = (
            tr("done_settings_body", access=access, app=who)
            if access
            else tr("done_settings_body_plain", app=who)
        )
    elif action == "mark_expected":
        access = _access(event)
        headline = tr("done_expected", app=who)
        body = (
            tr("done_expected_body", access=access, app=who)
            if access
            else tr("done_expected_body_plain", app=who)
        )
    report: dict[str, Any] = {
        "action": action,
        "headline": headline,
        "body": body,
        "subject": decision.subject,
        "destination": decision.destination,
    }
    if action == "reject_optional":
        # The page carries this one out, and a banner it cannot find the reject
        # control in is reported as exactly that rather than as a success.
        report["failed"] = {
            "headline": tr("reject_not_found"),
            "body": tr("reject_not_found_body"),
            "subject": decision.subject,
            "destination": decision.destination,
        }
    return report


def _field_names(event: PrivacyEvent, field_ids: list[str]) -> list[str]:
    """What the blanked fields asked for, as the category each one holds."""
    if not isinstance(event, FormObservedEvent):
        return []
    wanted = set(field_ids)
    return named(
        [
            field.category
            for field in event.fields
            if field.field_id in wanted and field.category is not None
        ]
    )
