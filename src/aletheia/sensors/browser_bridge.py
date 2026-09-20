from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from aletheia.analysis.forms import label_field
from aletheia.analysis.purpose import infer_purpose
from aletheia.core.events import (
    EVENT_ADAPTER,
    FormContext,
    FormObservedEvent,
    PrivacyEvent,
    Requester,
)


def enrich_browser_requester(
    requester: Requester, signals: dict[str, Any] | None = None
) -> Requester:
    signals = signals or {}
    headings = signals.get("headings", [])
    inferred = infer_purpose(
        origin=requester.origin,
        title=str(signals.get("title", ""))[:500],
        meta=str(signals.get("meta", ""))[:1000],
        headings=[str(item)[:300] for item in headings[:10]] if isinstance(headings, list) else [],
        cta=str(signals.get("cta", ""))[:500],
        url_path=str(signals.get("url_path", ""))[:500],
        app_name=requester.display_name,
    )
    return requester.model_copy(
        update={"purpose": inferred.purpose, "purpose_confidence": inferred.confidence}
    )


def parse_browser_event(payload: dict[str, Any]) -> PrivacyEvent:
    event = EVENT_ADAPTER.validate_python(payload.get("event", payload))
    event.requester = enrich_browser_requester(event.requester, payload.get("signals", {}))
    if isinstance(event, FormObservedEvent):
        event.fields = [
            label_field(field.model_copy(update={"category": None, "confidence": 0.0}))
            for field in event.fields
        ]
        event.data_categories = []
    return event


def prepare_context(payload: dict[str, Any]) -> dict[str, Any]:
    origin = str(payload.get("origin", ""))
    # Name the site. Every warning raised from page context used to open with the
    # word "Website" because nothing filled this in, which told the reader nothing
    # about which of their open tabs it was talking about.
    requester = Requester(
        origin=origin,
        display_name=str(payload.get("display_name", "") or urlsplit(origin).hostname or "Website"),
    )
    requester = enrich_browser_requester(requester, payload.get("signals", {}))
    result = dict(payload)
    result["purpose"] = requester.purpose
    result["purpose_confidence"] = requester.purpose_confidence
    result["requester"] = requester.model_dump(mode="json")
    forms = result.get("forms")
    if isinstance(forms, dict):
        forms["context"] = _form_context(forms.get("context"), payload.get("signals", {}))
    return result


def _form_context(value: object, signals: dict[str, Any] | None) -> dict[str, Any]:
    """Fold the page's own title and headings into the form's context.

    A form element carries a submit label and maybe a legend; what the page says it is
    for usually sits in the surrounding markup, and that is the part that separates a
    registration form from a mailing-list box.
    """
    signals = signals or {}
    context = FormContext.model_validate(value if isinstance(value, dict) else {})
    headings = signals.get("headings", [])
    if not context.page_title:
        context = context.model_copy(update={"page_title": str(signals.get("title", ""))[:300]})
    if not context.heading and isinstance(headings, list) and headings:
        context = context.model_copy(update={"heading": str(headings[0])[:300]})
    if not context.nearby_text:
        context = context.model_copy(update={"nearby_text": str(signals.get("meta", ""))[:500]})
    return context.model_dump(mode="json")
