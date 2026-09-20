from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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


def _pdf(*lines: str, rotate: int = 0) -> bytes:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    for index, line in enumerate(lines):
        canvas.drawString(72, 700 - 20 * index, line)
    canvas.showPage()
    canvas.save()
    if not rotate:
        return buffer.getvalue()
    # A page that is shown turned, the way a scanner or a viewer's rotate leaves it:
    # the content stays where it was drawn and /Rotate says how to display it.
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buffer.getvalue())))
    writer.pages[0].rotate(rotate)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _boxes(content: bytes) -> list[tuple[float, float, float, float]]:
    """The bars painted into the page, read back from the marked blocks."""
    import io
    import re

    from pypdf import PdfReader

    page = PdfReader(io.BytesIO(content)).pages[0]
    painted = b"".join(entry.get_object().get_data() for entry in page["/Contents"])
    return [
        (float(x), float(y), float(x) + float(w), float(y) + float(h))
        for x, y, w, h in re.findall(
            rb"/PrivacyGuardian <<[^>]*>> BDC q 0 g ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re f Q EMC",
            painted,
        )
    ]


def _render(content: bytes) -> Any:
    """The page as a viewer that ignores annotations would paint it."""
    import pypdfium2

    return pypdfium2.PdfDocument(content)[0].render(scale=2, draw_annots=False).to_pil()


def test_pdf_with_text_gets_a_box_per_detail_and_keeps_the_rest_intact() -> None:
    import io

    from pypdf import PdfReader

    data = _pdf(
        "Quarterly notes for the team",
        "Contact: casey.person@example.test for details",
        "Nothing else of note on this page.",
    )
    document = extract_document(data, "notes.pdf")
    result = redact_document(data, "notes.pdf", document)
    assert result.verified and result.boxes == 1
    reader = PdfReader(io.BytesIO(result.content))
    # The bar is page content, not an annotation, so every viewer paints it.
    assert "/Annots" not in reader.pages[0]
    [(x0, y0, x1, y1)] = _boxes(result.content)
    # It sits on the contact line, around the address, and nowhere else.
    assert 675 < y0 < 682 and 688 < y1 < 696 and x0 > 100 and x1 < 400
    rendered = _render(result.content).convert("RGB")
    assert rendered.getpixel((int((x0 + x1)), int((842 - (y0 + y1) / 2) * 2))) == (0, 0, 0)
    assert rendered.getpixel((int(80 * 2), int((842 - 700) * 2))) != (0, 0, 0)
    assert "Quarterly notes for the team" in reader.pages[0].extract_text()
    restored = unredact_document(result.content, "redacted-document.pdf")
    assert restored.boxes == 1
    # The original content stream comes back exactly as it was.
    original = PdfReader(io.BytesIO(data)).pages[0].get_contents().get_data()
    assert PdfReader(io.BytesIO(restored.content)).pages[0].get_contents().get_data() == original


def test_every_flagged_detail_is_covered_even_when_a_fresh_look_would_miss_it() -> None:
    """The card says what was found; the copy covers exactly that, whatever a rescan says."""
    from privacy_guardian.core.events import Finding

    data = _pdf("Quarterly notes for the team", "Prepared by the finance office.")
    document = extract_document(data, "notes.pdf")
    text = document.pages[0].text
    start = text.index("finance office")
    flagged = [
        Finding(
            category=DataCategory.EMPLOYMENT,
            confidence=0.9,
            span_ref=f"{start}:{start + len('finance office')}",
            page=1,
        )
    ]
    result = redact_document(data, "notes.pdf", document, findings=flagged)
    assert result.boxes == 1
    [(x0, y0, x1, y1)] = _boxes(result.content)
    # The second line, at y=680: the bar sits on it.
    assert 675 < y0 < 682 and 688 < y1 < 696
    # A flagged detail that is not on the page refuses the copy rather than skipping it.
    missing = [Finding(category=DataCategory.FULL_NAME, confidence=0.9, span_ref="0:5", page=1)]
    document.pages[0].text = "Ghost " + text
    with pytest.raises(ValueError):
        redact_document(data, "notes.pdf", document, findings=missing)


def test_a_rotated_page_gets_its_box_where_the_text_is_shown() -> None:
    data = _pdf("Contact: casey.person@example.test for details", rotate=90)
    document = extract_document(data, "notes.pdf")
    result = redact_document(data, "notes.pdf", document)
    assert result.boxes == 1
    [(x0, y0, x1, y1)] = _boxes(result.content)
    # In the page's own space the line is still at y=700; drawn there, it lands on the
    # text however the page is turned.
    assert 690 < y0 < 700 and 705 < y1 < 715
    rendered = _render(result.content).convert("RGB")
    # Rendered as displayed (turned 90 degrees clockwise), the line now runs down the
    # page 700 units from its left edge, and the bar is on it.
    assert abs(rendered.size[0] - 842 * 2) <= 1 and abs(rendered.size[1] - 595 * 2) <= 1
    assert rendered.getpixel((int((y0 + y1) / 2 * 2), int((x0 + x1) / 2 * 2))) == (0, 0, 0)
    assert rendered.getpixel((int(300 * 2), int((x0 + x1) / 2 * 2))) != (0, 0, 0)


def test_neighbouring_boxes_fuse_into_one_bar_whichever_comes_first() -> None:
    """Two words on a line whose bottoms round to different lines still make one bar."""
    from privacy_guardian.analysis.documents.redact import _merge

    right = (197.5, 502.5, 267.0, 514.0)
    left = (174.5, 503.0, 196.0, 514.0)
    assert _merge([right, left]) == [(174.5, 502.5, 267.0, 514.0)]
    assert _merge([left, right]) == [(174.5, 502.5, 267.0, 514.0)]
    apart = (300.0, 503.0, 340.0, 514.0)
    assert len(_merge([left, right, apart])) == 2


def test_boxes_merged_into_the_page_content_by_another_tool_can_still_be_taken_off() -> None:
    import io

    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, StreamObject

    data = _pdf("Contact: casey.person@example.test for details")
    result = redact_document(data, "notes.pdf", extract_document(data, "notes.pdf"))
    # A compressor folds the three content streams into one and drops our keys.
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(result.content)))
    page = writer.pages[0]
    merged = StreamObject()
    merged.set_data(b"\n".join(entry.get_object().get_data() for entry in page["/Contents"]))
    page[NameObject("/Contents")] = writer._add_object(merged)
    output = io.BytesIO()
    writer.write(output)
    flattened = output.getvalue()
    assert count_redaction_marks(flattened, "flat.pdf") == 1
    assert _render(flattened).convert("RGB").getpixel((int(200 * 2), int((842 - 703) * 2))) == (
        0,
        0,
        0,
    )
    restored = unredact_document(flattened, "flat.pdf")
    assert restored.boxes == 1
    assert count_redaction_marks(restored.content, restored.filename) == 0
    assert _render(restored.content).convert("RGB").getpixel(
        (int(200 * 2), int((842 - 703) * 2))
    ) != (0, 0, 0)
    assert (
        "casey.person@example.test"
        in PdfReader(io.BytesIO(restored.content)).pages[0].extract_text()
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
