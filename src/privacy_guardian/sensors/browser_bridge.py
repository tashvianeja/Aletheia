from __future__ import annotations

from typing import Any

from privacy_guardian.analysis.forms import label_field
from privacy_guardian.analysis.purpose import infer_purpose
from privacy_guardian.core.events import EVENT_ADAPTER, FormObservedEvent, PrivacyEvent, Requester


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
    requester = Requester(
        origin=str(payload.get("origin", "")),
        display_name=str(payload.get("display_name", "Website")),
    )
    requester = enrich_browser_requester(requester, payload.get("signals", {}))
    result = dict(payload)
    result["purpose"] = requester.purpose
    result["purpose_confidence"] = requester.purpose_confidence
    result["requester"] = requester.model_dump(mode="json")
    return result
