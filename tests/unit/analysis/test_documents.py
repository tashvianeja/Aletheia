from __future__ import annotations

from pathlib import Path

from privacy_guardian.analysis.documents import extract_document
from privacy_guardian.analysis.pii import detect_pii
from privacy_guardian.analysis.worker import analyze_payload, redact_payload
from privacy_guardian.core.events import DataCategory

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_synthetic_passport_extracts_required_identity_categories() -> None:
    path = FIXTURES / "passport_synthetic.pdf"
    document = extract_document(path.read_bytes(), path.name)
    text = "\n".join(page.text for page in document.pages)
    findings = [
        finding for page in document.pages for finding in detect_pii(page.text, page=page.number)
    ]
    categories = {finding.category for finding in findings} | document.metadata_categories
    assert document.partial is False
    assert document.document_type == "identity_document"
    assert {
        DataCategory.GOVERNMENT_ID_PASSPORT,
        DataCategory.FULL_NAME,
        DataCategory.DOB,
        DataCategory.BIOMETRIC_PHOTO,
    } <= categories
    assert "SYNTHETIC PASSPORT" in text


def test_analyze_redact_rescan_removes_all_detected_passport_pii() -> None:
    path = FIXTURES / "passport_synthetic.pdf"
    analysis = analyze_payload(
        {"kind": "document", "filename": path.name, "data": path.read_bytes()}
    )
    categories = {finding.category for finding in analysis.findings}
    assert {
        DataCategory.GOVERNMENT_ID_PASSPORT,
        DataCategory.FULL_NAME,
        DataCategory.DOB,
        DataCategory.BIOMETRIC_PHOTO,
    } <= categories
    assert analysis.payload_ref is not None
    redacted = redact_payload(analysis.payload_ref)
    assert redacted.verified is True
    rescanned = analyze_payload(
        {"kind": "document", "filename": redacted.filename, "data": redacted.content}
    )
    assert rescanned.findings == []


def test_gps_jpeg_metadata_is_detected_and_strip_action_removes_it() -> None:
    path = FIXTURES / "social_photo_gps_synthetic.jpg"
    analysis = analyze_payload(
        {"kind": "document", "filename": path.name, "data": path.read_bytes()}
    )
    assert any(finding.category == DataCategory.LOCATION_PRECISE for finding in analysis.findings)
    assert analysis.payload_ref is not None
    stripped = redact_payload(analysis.payload_ref, strip_metadata=True)
    assert stripped.verified
    rescanned = extract_document(stripped.content, stripped.filename)
    assert DataCategory.LOCATION_PRECISE not in rescanned.metadata_categories
