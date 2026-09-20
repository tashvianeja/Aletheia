"""Deciding when two observations are the same thing to say.

A page reports its context many times over: once when it loads, again when the
consent banner animates in, again when the next advertising script fires. Each
report is a fresh event, and without this the person is shown the same warning
once per report. A notice signature answers "have we already said this?" by
naming only what makes a warning different, and ignoring the detail that drifts
between two looks at the same page.
"""

from __future__ import annotations

from privacy_guardian.core.events import (
    ConsentBannerEvent,
    PermissionRequestEvent,
    PrivacyEvent,
    RedactedDocumentEvent,
    ScreenCaptureEvent,
    StartupRegistrationEvent,
    SystemAccessEvent,
    TrackingEvent,
)

# Warnings that are always raised afresh, either because they hold up something the
# person is doing right now — reusing one would apply an earlier answer to a new
# action, cancelling a second upload because the first was cancelled, or worse,
# allowing it because the first was allowed — or because they report a moment rather
# than a standing state, and the second clipboard read is a second exposure.
# A form sitting on the page is not in that group. It is a standing state — this form
# asks for these things — and it reports itself again on every keystroke, so keying it
# on what it asks for is what makes it one card about the whole form rather than a
# fresh card per field per pass. Submitting it stays here: that holds up a real send.
ALWAYS_ASK = frozenset({"file_upload", "form_submit", "policy_document", "clipboard_read"})


def notice_signature(event: PrivacyEvent) -> str:
    """Identify the warning this event would raise, or "" if it must always be raised."""
    if event.event_type in ALWAYS_ASK:
        return ""
    parts: list[str]
    if isinstance(event, TrackingEvent):
        # There is one thing to say about a page here — that it is building an
        # advertising profile — and every mechanism behind it arrives in its own
        # wave: the tracker requests as the page loads, the fingerprint when that
        # script gets its turn, the pixels later still. Keying on the mechanisms
        # made each wave a separate warning, so the person was shown the same card
        # two or three times over, each one listing a little more than the last.
        # A later look sharpens the card already up; it is not a second card.
        parts = []
    elif isinstance(event, ConsentBannerEvent):
        # Vendor counts and button geometry move with every banner re-render.
        parts = [event.cmp, *sorted(set(event.dark_patterns)), *sorted(set(event.purposes))]
    elif isinstance(event, PermissionRequestEvent):
        parts = [event.permission, event.state]
    elif isinstance(event, SystemAccessEvent):
        parts = sorted(set(event.accesses))
    elif isinstance(event, ScreenCaptureEvent):
        parts = [f"active={event.active}"]
    elif isinstance(event, StartupRegistrationEvent):
        parts = [event.mechanism]
    elif isinstance(event, RedactedDocumentEvent):
        # One card per file, however many times it is brought to the front.
        parts = [event.path]
    else:
        parts = sorted(category.value for category in event.data_categories)
    return "\x1f".join([event.event_type, event.requester.key, *parts])
