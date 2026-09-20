from __future__ import annotations

from pathlib import Path

from privacy_guardian.analysis.documents import extract_document
from privacy_guardian.analysis.documents.extract import ExtractedDocument, Page
from privacy_guardian.analysis.documents.redact import redact_document, unredact_document
from privacy_guardian.analysis.pii import detect_pii
from privacy_guardian.analysis.worker import (
    analyze_payload,
    count_redaction_marks,
    redact_payload,
    unredact_payload,
)
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
    """A redacted copy is the same file with black boxes over it, and can be restored."""
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
    assert redacted.boxes >= 1
    assert count_redaction_marks(redacted.content, redacted.filename) == redacted.boxes
    # The boxes are drawn on the original, so the original's own text is still what
    # lies beneath them; that is what makes restoring possible.
    restored = unredact_payload(redacted.content, redacted.filename)
    assert restored.boxes == redacted.boxes
    assert count_redaction_marks(restored.content, restored.filename) == 0
    before = "\n".join(page.text for page in extract_document(path.read_bytes(), path.name).pages)
    after = "\n".join(
        page.text for page in extract_document(restored.content, restored.filename).pages
    )
    assert after == before


def test_pdf_with_text_gets_a_box_per_detail_and_keeps_the_rest_intact() -> None:
    import io

    from pypdf import PdfReader
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    canvas.drawString(72, 700, "Quarterly notes for the team")
    canvas.drawString(72, 680, "Contact: casey.person@example.test for details")
    canvas.drawString(72, 660, "Nothing else of note on this page.")
    canvas.showPage()
    canvas.save()
    data = buffer.getvalue()
    document = extract_document(data, "notes.pdf")
    result = redact_document(data, "notes.pdf", document)
    assert result.verified and result.boxes == 1
    reader = PdfReader(io.BytesIO(result.content))
    annotation = reader.pages[0]["/Annots"][0].get_object()
    assert annotation["/Subtype"] == "/Square" and annotation["/T"] == "Privacy Guardian"
    x0, y0, x1, y1 = (float(value) for value in annotation["/Rect"])
    # The bar sits on the contact line, around the address, and nowhere else.
    assert 675 < y0 < 682 and 688 < y1 < 696 and x0 > 100 and x1 < 400
    assert "Quarterly notes for the team" in reader.pages[0].extract_text()
    restored = unredact_document(result.content, "redacted-document.pdf")
    assert (
        restored.boxes == 1
        and "/Annots" not in PdfReader(io.BytesIO(restored.content)).pages[0]
        or not PdfReader(io.BytesIO(restored.content)).pages[0]["/Annots"]
    )


def test_image_redaction_paints_boxes_and_can_restore_the_pixels() -> None:
    import io

    from PIL import Image

    original = Image.new("RGB", (200, 60), "white")
    for x in range(40, 160):
        for y in range(20, 40):
            original.putpixel((x, y), (200, 30, 30))
    buffer = io.BytesIO()
    original.save(buffer, format="PNG")
    text = "Contact casey.person@example.test now"
    start = text.index("casey")
    end = start + len("casey.person@example.test")
    document = ExtractedDocument(
        pages=[Page(text, 1, [(0, 7, 2, 22, 30, 16), (start, end, 40, 20, 120, 20)])]
    )
    result = redact_document(buffer.getvalue(), "photo.png", document)
    assert result.verified and result.boxes == 1
    assert count_redaction_marks(result.content, result.filename) == 1
    with Image.open(io.BytesIO(result.content)) as redacted:
        assert redacted.getpixel((100, 30)) == (0, 0, 0)
        assert redacted.getpixel((10, 10)) == (255, 255, 255)
    restored = unredact_document(result.content, result.filename)
    with Image.open(io.BytesIO(restored.content)) as image:
        assert image.getpixel((100, 30)) == (200, 30, 30)
        assert image.tobytes() == original.tobytes()
    assert count_redaction_marks(restored.content, restored.filename) == 0
    assert count_redaction_marks(buffer.getvalue(), "photo.png") == 0


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


def test_five_mib_plain_text_scans_pii_near_end_without_partial_result() -> None:
    size = 5 * 1024**2
    record = b"Synthetic ordinary service record with no personal details.\n"
    late_pii = b"Final contact: lateperson@example.test\n"
    content = (record * (size // len(record) + 1))[: size - len(late_pii)] + late_pii
    assert len(content) == size

    analysis = analyze_payload(
        {"kind": "document", "filename": "synthetic-records.txt", "data": content}
    )

    emails = [finding for finding in analysis.findings if finding.category == DataCategory.EMAIL]
    assert len(emails) == 1
    _start, end = map(int, emails[0].span_ref.split(":"))
    assert end > size - 100
    assert analysis.partial is False
