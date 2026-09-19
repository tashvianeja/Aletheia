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
ALWAYS_ASK = frozenset(
    {"file_upload", "form_submit", "form_observed", "policy_document", "clipboard_read"}
)


def notice_signature(event: PrivacyEvent) -> str:
    """Identify the warning this event would raise, or "" if it must always be raised."""
    if event.event_type in ALWAYS_ASK:
        return ""
    parts: list[str]
    if isinstance(event, TrackingEvent):
        # Tracker domains and confidence both climb as the page keeps loading; the
        # mechanisms at work are what make one tracking warning different from another.
        parts = sorted(set(event.signals)) + [f"fingerprinting={event.fingerprinting}"]
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
    else:
        parts = sorted(category.value for category in event.data_categories)
    return "\x1f".join([event.event_type, event.requester.key, *parts])
