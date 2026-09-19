from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from uuid import uuid4

from pydantic import BaseModel, Field

from privacy_guardian.analysis.consent import ConsentSnapshot, analyze_consent
from privacy_guardian.analysis.documents import (
    ExtractedDocument,
    RedactionResult,
    extract_document,
    redact_document,
)
from privacy_guardian.analysis.documents.extract import MAX_BYTES, SAMPLE_BYTES
from privacy_guardian.analysis.forms import FieldAssessment, analyze_fields
from privacy_guardian.analysis.pii import detect_pii
from privacy_guardian.analysis.policy import analyze_policy, analyze_terms
from privacy_guardian.analysis.tracking import TrackingSnapshot, analyze_tracking
from privacy_guardian.core.events import DataCategory, Finding, FormContext, FormField


class AnalysisResult(BaseModel):
    payload_ref: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    document_type: str = "generic"
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)
    profile: dict[str, object] = Field(default_factory=dict)
    fields: list[FieldAssessment] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)


@dataclass
class _Payload:
    data: bytes
    filename: str
    document: ExtractedDocument
    expires: float


_PAYLOADS: OrderedDict[str, _Payload] = OrderedDict()
_MAX_TOTAL = 150 * 1024 * 1024


def _expire() -> None:
    now = time.monotonic()
    for handle in list(_PAYLOADS):
        if _PAYLOADS[handle].expires < now:
            del _PAYLOADS[handle]
    while len(_PAYLOADS) > 8 or sum(len(item.data) for item in _PAYLOADS.values()) > _MAX_TOTAL:
        _PAYLOADS.popitem(last=False)


def warm_analysis() -> dict[str, bool]:
    from privacy_guardian.analysis.pii.detector import _ner
    from privacy_guardian.analysis.policy.analyzer import _segmenter

    _segmenter()
    return {"ner_ready": _ner() is not None}


def analyze_payload(payload: dict[str, object]) -> AnalysisResult:
    _expire()
    kind = str(payload.get("kind", "document" if "data" in payload else "text"))
    purpose = str(payload.get("purpose", "unknown"))
    if kind == "document":
        data = payload.get("data", b"")
        if not isinstance(data, bytes):
            raise ValueError("Document payload requires bytes")
        filename = str(payload.get("filename", "document.txt"))
        original_size = payload.get("original_size")
        timeout = payload.get("timeout", 20)
        timeout_seconds = (
            min(120.0, max(0.05, float(timeout)))
            if isinstance(timeout, (float, int, str))
            else 20.0
        )
        extraction_start = time.perf_counter()
        document = extract_document(
            data,
            filename,
            timeout=timeout_seconds,
            partial=bool(payload.get("partial", False)),
            original_size=int(original_size) if isinstance(original_size, (int, str)) else None,
        )
        extraction_ms = (time.perf_counter() - extraction_start) * 1000
        pii_start = time.perf_counter()
        findings = [
            finding
            for page in document.pages
            for finding in detect_pii(page.text, page=page.number, use_ner=True)
        ]
        for category in document.metadata_categories:
            findings.append(
                Finding(
                    category=category,
                    confidence=0.95,
                    span_ref="metadata",
                    stable_hash="metadata:" + category.value,
                )
            )
        handle = str(uuid4())
        _PAYLOADS[handle] = _Payload(data, filename, document, time.monotonic() + 120)
        _expire()
        return AnalysisResult(
            payload_ref=handle,
            findings=findings,
            document_type=document.document_type,
            partial=document.partial,
            warnings=document.warnings,
            timings_ms={
                "extraction": extraction_ms,
                "pii": (time.perf_counter() - pii_start) * 1000,
            },
        )
    if kind == "text":
        text = str(payload.get("text", ""))
        encoded = text.encode("utf-8", errors="replace")
        partial = len(encoded) > MAX_BYTES
        if partial:
            text = (
                encoded[:SAMPLE_BYTES].decode("utf-8", errors="replace")
                + "\n"
                + encoded[-SAMPLE_BYTES:].decode("utf-8", errors="replace")
            )
        return AnalysisResult(
            findings=detect_pii(text, use_ner=bool(payload.get("use_ner", False))),
            partial=partial,
            warnings=(
                ["Large text sampled: first and last 5 MiB; unsampled content was not checked."]
                if partial
                else []
            ),
        )
    if kind in {"policy", "privacy_policy"}:
        profile = analyze_policy(str(payload.get("text", "")), purpose)
        return AnalysisResult(
            profile=profile.model_dump(mode="json"),
            partial=profile.partial,
            warnings=profile.warnings,
        )
    if kind == "terms":
        terms = analyze_terms(str(payload.get("text", "")))
        return AnalysisResult(
            profile=terms.model_dump(mode="json"),
            partial=terms.partial,
        )
    if kind == "forms":
        fields_value = payload.get("fields", [])
        if not isinstance(fields_value, list):
            raise ValueError("Fields must be a list")
        fields = [FormField.model_validate(field) for field in fields_value]
        confidence = payload.get("purpose_confidence", 1.0)
        context_value = payload.get("context")
        context = FormContext.model_validate(
            context_value if isinstance(context_value, dict) else {}
        )
        return AnalysisResult(
            fields=analyze_fields(
                fields,
                purpose,
                float(confidence) if isinstance(confidence, (float, int, str)) else 1.0,
                context,
            )
        )
    if kind == "consent":
        consent = analyze_consent(ConsentSnapshot.model_validate(payload.get("snapshot", {})))
        return AnalysisResult(profile=consent.model_dump(mode="json"))
    if kind == "tracking":
        tracking = analyze_tracking(
            TrackingSnapshot.model_validate(payload.get("snapshot", {})),
            str(payload.get("tracker_path", "")),
        )
        return AnalysisResult(profile=tracking.model_dump(mode="json"))
    raise ValueError("Unknown analysis kind")


def redact_payload(
    handle: str, categories: list[str] | None = None, strip_metadata: bool = False
) -> RedactionResult:
    _expire()
    stored = _PAYLOADS.get(handle)
    if stored is None:
        raise ValueError("Document handle expired; select the file again")
    selected = (
        {DataCategory(category) for category in categories} if categories is not None else None
    )
    result = redact_document(
        stored.data, stored.filename, stored.document, selected, strip_metadata=strip_metadata
    )
    del _PAYLOADS[handle]
    return result


def release_payload(handle: str) -> bool:
    return _PAYLOADS.pop(handle, None) is not None
