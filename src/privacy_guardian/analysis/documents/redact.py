from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from privacy_guardian.analysis.documents.extract import ExtractedDocument, extract_document
from privacy_guardian.analysis.pii import detect_pii, find_matches, redact_text
from privacy_guardian.core.events import DataCategory, Finding

# How a redaction box announces itself inside the file it was drawn on, so the same
# file can be recognised later and the box taken off again. In a PDF the box is
# painted into the page's own content, inside a marked-content block carrying this
# tag, so every viewer shows it: a box that lives only in an annotation is one that
# Preview, and any viewer that skips annotations, does not draw. The painting sits
# in streams of its own, keyed with STREAM_KEY, around the untouched original, so a
# restored copy is the original content exactly as it was. In a PNG the covered
# pixels ride along in a text chunk under PNG_MARK_KEY. All of it survives a re-save
# or a compressor that keeps page content, which is what makes a restored copy of a
# compressed file possible.
MARK_TAG = "/PrivacyGuardian"
STREAM_KEY = "/PGRedaction"
PNG_MARK_KEY = "pg-redaction"
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"})
TEXT_SUFFIXES = frozenset({".txt", ".csv", ".json", ".md", ".log", ""})
# OCR runs on a page rendered at twice its natural size (extract.py, scale=2).
OCR_SCALE = 2.0
Box = tuple[float, float, float, float]
Span = tuple[int, int]
_MARK = re.compile(rb"/PrivacyGuardian\s*<<[^>]*>>\s*BDC")


class RedactionResult(BaseModel):
    content: bytes = Field(repr=False)
    filename: str
    mime: str
    verified: bool
    warnings: list[str] = Field(default_factory=list)
    # How many boxes were drawn (or, for a restored copy, taken off).
    boxes: int = 0


def _wanted(category: Any, categories: set[DataCategory] | None) -> bool:
    return categories is None or category in categories


def _flagged_spans(
    findings: list[Finding] | None, page: int, categories: set[DataCategory] | None
) -> list[Span]:
    """The spans the analysis flagged on this page, as offsets into its text."""
    spans: list[Span] = []
    for finding in findings or []:
        if finding.page not in (None, page) or not _wanted(finding.category, categories):
            continue
        start, _, end = finding.span_ref.partition(":")
        if start.isdigit() and end.isdigit() and int(end) > int(start):
            spans.append((int(start), int(end)))
    return spans


def _ocr_boxes(
    page: Any, categories: set[DataCategory] | None, flagged: list[Span] | None = None
) -> tuple[list[Box], int]:
    """Pixel boxes for every flagged and every detected match on an OCR'd page.

    Returns the boxes and how many spans had no token under them.
    """
    spans = list(flagged or [])
    spans.extend(
        (match.start, match.end)
        for match in find_matches(page.text, use_ner=True)
        if _wanted(match.category, categories)
    )
    boxes: list[Box] = []
    unplaced = 0
    for start, end in dict.fromkeys(spans):
        hits = [
            (left - 2, top - 2, left + width + 2, top + height + 2)
            for token_start, token_end, left, top, width, height in page.boxes
            if start < token_end and end > token_start
        ]
        if not hits:
            unplaced += 1
        boxes.extend(hits)
    return boxes, unplaced


def _compact(text: str) -> str:
    return "".join(text.split())


def _pdf_page_boxes(
    layout_page: Any,
    categories: set[DataCategory] | None,
    values: list[str],
    shown_height: float,
    turned: bool = False,
) -> tuple[list[Box], int]:
    """Boxes, in the page's displayed space, for the matches on a page with its own text.

    `values` are the flagged strings themselves, found again here word by word and
    regardless of spacing, because the text the analysis read and the words the
    layout gives back are not laid out identically. `shown_height` is the height of
    the page as displayed: the layout measures a word's top from there, but reports
    the unrotated height as the page's, so a turned page cannot be trusted for it.
    Returns the boxes and how many values or matches could not be placed: one with
    no word under it is one the box cannot cover, and the copy is not certified.
    """
    # Reading in content order keeps a column's words together, but that reading
    # breaks the letters of a turned page apart; there, cluster by position instead.
    words = layout_page.extract_words(keep_blank_chars=False, use_text_flow=not turned)
    text = ""
    spans: list[tuple[int, int, Any]] = []
    # Words on one line share a top; on a page shown turned by a quarter, a line runs
    # down the page and its words share a left edge instead.
    line_key = "x0" if turned else "top"
    previous: float | None = None
    for word in words:
        if text:
            text += " " if previous is not None and abs(word[line_key] - previous) < 3 else "\n"
        start = len(text)
        text += str(word["text"])
        spans.append((start, len(text), word))
        previous = float(word[line_key])

    def rect(word: Any) -> Box:
        return (
            float(word["x0"]) - 1.5,
            shown_height - float(word["bottom"]) - 1.5,
            float(word["x1"]) + 1.5,
            shown_height - float(word["top"]) + 1.5,
        )

    boxes: list[Box] = []
    unplaced = 0
    for match in find_matches(text, use_ner=True):
        if not _wanted(match.category, categories):
            continue
        hits = [word for start, end, word in spans if match.start < end and match.end > start]
        if not hits:
            unplaced += 1
        boxes.extend(rect(word) for word in hits)
    # Every word's characters, run together, with the word each character came from.
    joined = ""
    owner: list[int] = []
    for index, (_start, _end, word) in enumerate(spans):
        compact = _compact(str(word["text"]))
        joined += compact
        owner.extend([index] * len(compact))
    for value in dict.fromkeys(_compact(value) for value in values):
        if not value:
            continue
        found = False
        position = joined.find(value)
        while position >= 0:
            found = True
            boxes.extend(
                rect(spans[index][2])
                for index in sorted(set(owner[position : position + len(value)]))
            )
            position = joined.find(value, position + 1)
        if not found:
            unplaced += 1
    return boxes, unplaced


def _merge(boxes: list[Box]) -> list[Box]:
    """Fuse boxes that touch on one line, so a name is one bar rather than two.

    Two neighbours whose bottoms round to different lines can arrive in either
    order, so the fused bar takes the outer edges of both rather than trusting the
    first one seen for its left edge.
    """
    merged: list[Box] = []
    for box in sorted(boxes, key=lambda item: (round(item[1]), item[0])):
        if merged:
            last = merged[-1]
            same_line = abs(last[1] - box[1]) < 2 and abs(last[3] - box[3]) < 2
            touching = box[0] <= last[2] + 6 and box[2] >= last[0] - 6
            if same_line and touching:
                merged[-1] = (
                    min(last[0], box[0]),
                    min(last[1], box[1]),
                    max(last[2], box[2]),
                    max(last[3], box[3]),
                )
                continue
        merged.append(box)
    return merged


def _user_space(box: Box, rotation: int, reference: tuple[float, float, float, float]) -> Box:
    """A box in the page as displayed, mapped onto the page's own coordinates.

    Both the layout and the OCR render see the page the way a viewer shows it, with
    /Rotate applied; the content stream is drawn in the page's unrotated space.
    """
    x0, y0, x1, y1 = reference

    def point(x: float, y: float) -> tuple[float, float]:
        if rotation == 90:
            return x1 - y, y0 + x
        if rotation == 180:
            return x1 - x, y1 - y
        if rotation == 270:
            return x0 + y, y1 - x
        return x0 + x, y0 + y

    corners = [point(box[0], box[1]), point(box[2], box[3])]
    return (
        min(corner[0] for corner in corners),
        min(corner[1] for corner in corners),
        max(corner[0] for corner in corners),
        max(corner[1] for corner in corners),
    )


def _box_content(boxes: list[Box]) -> bytes:
    """The painting: close the wrap around the original, then one marked block per box."""
    parts = [b"\nQ\n"]
    for number, (x0, y0, x1, y1) in enumerate(boxes, 1):
        parts.append(
            f"{MARK_TAG} <</Name /pg-redaction-{number}>> BDC q 0 g "
            f"{x0:.2f} {y0:.2f} {x1 - x0:.2f} {y1 - y0:.2f} re f Q EMC\n".encode()
        )
    return b"".join(parts)


def _content_entries(page: Any) -> list[Any]:
    """The page's content streams as they are referenced, unresolved."""
    from pypdf.generic import ArrayObject

    if "/Contents" not in page:
        return []
    raw = page.raw_get("/Contents")
    resolved = raw.get_object() if hasattr(raw, "get_object") else raw
    if isinstance(resolved, ArrayObject):
        return list(resolved)
    return [raw]


def _paint_boxes(writer: Any, page: Any, boxes: list[Box]) -> None:
    """Wrap the page's own content in q/Q and paint the boxes after it, in streams of ours."""
    from pypdf.generic import ArrayObject, NameObject, StreamObject

    opening = StreamObject()
    opening.set_data(b"q\n")
    opening[NameObject(STREAM_KEY)] = NameObject("/Open")
    closing = StreamObject()
    closing.set_data(_box_content(boxes))
    closing[NameObject(STREAM_KEY)] = NameObject("/Boxes")
    page[NameObject("/Contents")] = ArrayObject(
        [writer._add_object(opening), *_content_entries(page), writer._add_object(closing)]
    )


def _page_marks(page: Any) -> int:
    from pypdf.generic import StreamObject

    entries = [entry.get_object() for entry in _content_entries(page)]
    streams = [entry for entry in entries if isinstance(entry, StreamObject)]
    tagged = [stream for stream in streams if STREAM_KEY in stream]
    # Ours, when they are still separate; every stream, in case a tool merged them.
    return sum(len(_MARK.findall(stream.get_data())) for stream in (tagged or streams))


def _pdf_marks(data: bytes) -> int:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        return 0
    return sum(_page_marks(page) for page in reader.pages)


def _strip_marked_content(writer: Any, page: Any) -> int:
    """Take our marked blocks out of content a tool has merged with the page's own."""
    from pypdf.generic import ContentStream

    content = ContentStream(page.get_contents(), writer)
    kept = []
    depth = 0
    removed = 0
    for operands, operator in content.operations:
        if depth:
            if operator in (b"BDC", b"BMC"):
                depth += 1
            elif operator == b"EMC":
                depth -= 1
            continue
        if operator == b"BDC" and operands and str(operands[0]) == MARK_TAG:
            depth = 1
            removed += 1
            continue
        kept.append((operands, operator))
    content.operations = kept
    page.replace_contents(content)
    return removed


def _png_marks(data: bytes) -> int:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        raw = getattr(image, "text", {}).get(PNG_MARK_KEY, "")
    if not raw:
        return 0
    try:
        return len(json.loads(raw).get("boxes", []))
    except (ValueError, AttributeError):
        return 0


def redaction_marks(data: bytes, filename: str) -> int:
    """How many Privacy Guardian redaction boxes `data` carries, or 0 for none.

    A file that answers 0 either was never redacted this way, or has been through
    something that dropped the marks; either way there is nothing here to restore.
    """
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf" or data.startswith(b"%PDF-"):
            return _pdf_marks(data)
        if suffix == ".png" or data.startswith(b"\x89PNG"):
            return _png_marks(data)
    except Exception:
        return 0
    return 0


def _redact_pdf(
    data: bytes,
    document: ExtractedDocument,
    categories: set[DataCategory] | None,
    findings: list[Finding] | None,
) -> tuple[bytes, int, int]:
    """Paint a box over every flagged detail, on the document as it is.

    Nothing else in the file is touched: its images, fonts, layout and compressed
    streams all stay as they were. That is also what lets a restored copy be made
    from the redacted one, compressed or not.
    """
    import pdfplumber
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("Encrypted document requires a password")
    writer = PdfWriter(clone_from=reader)
    by_number = {page.number: page for page in document.pages}
    cover_whole = document.document_type == "identity_document" and (
        document.has_images or DataCategory.BIOMETRIC_PHOTO in (categories or set())
    )
    drawn = 0
    unplaced = 0
    with pdfplumber.open(io.BytesIO(data)) as layout:
        for index, page in enumerate(writer.pages):
            extracted = by_number.get(index + 1)
            media = page.mediabox
            mediabox = (
                float(media.left),
                float(media.bottom),
                float(media.right),
                float(media.top),
            )
            rotation = int(layout.pages[index].rotation) if index < len(layout.pages) else 0
            turned = rotation in (90, 270)
            flagged = _flagged_spans(findings, index + 1, categories)
            boxes: list[Box]
            if cover_whole:
                boxes = [mediabox]
            elif extracted is not None and extracted.boxes:
                # A scanned page: the OCR token boxes are pixels on a render of the page
                # as displayed, at OCR_SCALE, measured from its top-left corner.
                crop = page.cropbox
                cropbox = (float(crop.left), float(crop.bottom), float(crop.right), float(crop.top))
                shown_height = cropbox[2] - cropbox[0] if turned else cropbox[3] - cropbox[1]
                pixel_boxes, missed = _ocr_boxes(extracted, categories, flagged)
                unplaced += missed
                boxes = [
                    _user_space(
                        (
                            left / OCR_SCALE,
                            shown_height - bottom / OCR_SCALE,
                            right / OCR_SCALE,
                            shown_height - top / OCR_SCALE,
                        ),
                        rotation,
                        cropbox,
                    )
                    for left, top, right, bottom in pixel_boxes
                ]
            elif index < len(layout.pages):
                values = [extracted.text[start:end] for start, end in flagged] if extracted else []
                shown_boxes, missed = _pdf_page_boxes(
                    layout.pages[index],
                    categories,
                    values,
                    mediabox[2] - mediabox[0] if turned else mediabox[3] - mediabox[1],
                    turned,
                )
                unplaced += missed
                boxes = [_user_space(box, rotation, mediabox) for box in shown_boxes]
            else:
                boxes = []
            clipped = []
            for x0, y0, x1, y1 in _merge(boxes):
                box = (
                    max(mediabox[0], x0),
                    max(mediabox[1], y0),
                    min(mediabox[2], x1),
                    min(mediabox[3], y1),
                )
                if box[2] > box[0] and box[3] > box[1]:
                    clipped.append(box)
            if clipped:
                _paint_boxes(writer, page, clipped)
                drawn += len(clipped)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue(), drawn, unplaced


def _redact_image(
    data: bytes,
    document: ExtractedDocument,
    categories: set[DataCategory] | None,
    findings: list[Finding] | None,
) -> tuple[bytes, int, int]:
    """Paint the boxes onto the pixels, keeping what they covered inside the file."""
    from PIL import Image, ImageDraw
    from PIL.PngImagePlugin import PngInfo

    with Image.open(io.BytesIO(data)) as original:
        image = original.convert("RGB")
    boxes: list[Box]
    unplaced = 0
    if (
        DataCategory.BIOMETRIC_PHOTO in (categories or set())
        or document.document_type == "identity_document"
    ):
        boxes = [(0, 0, image.width, image.height)]
    else:
        boxes = []
        for page in document.pages:
            found, missed = _ocr_boxes(
                page, categories, _flagged_spans(findings, page.number, categories)
            )
            boxes.extend(found)
            unplaced += missed
    drawing = ImageDraw.Draw(image)
    covered: list[dict[str, Any]] = []
    for x0, y0, x1, y1 in _merge(boxes):
        left, top = max(0, int(x0)), max(0, int(y0))
        right, bottom = min(image.width, int(x1) + 1), min(image.height, int(y1) + 1)
        if right <= left or bottom <= top:
            continue
        crop = io.BytesIO()
        image.crop((left, top, right, bottom)).save(crop, format="PNG")
        covered.append(
            {
                "rect": [left, top, right, bottom],
                "png": base64.b64encode(crop.getvalue()).decode("ascii"),
            }
        )
        drawing.rectangle((left, top, right - 1, bottom - 1), fill="black")
    info = PngInfo()
    if covered:
        info.add_text(PNG_MARK_KEY, json.dumps({"version": 1, "boxes": covered}), zip=True)
    output = io.BytesIO()
    # New encoder, no exif/icc/xmp parameters: metadata bytes are not copied.
    image.save(output, format="PNG", pnginfo=info)
    return output.getvalue(), len(covered), unplaced


def unredact_document(data: bytes, filename: str) -> RedactionResult:
    """Take Privacy Guardian's boxes off a file it redacted, leaving all else as is."""
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem or "document"
    if suffix == ".pdf" or data.startswith(b"%PDF-"):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, NameObject, StreamObject

        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("Encrypted document requires a password")
        writer = PdfWriter(clone_from=reader)
        removed = 0
        for page in writer.pages:
            entries = _content_entries(page)
            kept = []
            taken = 0
            for entry in entries:
                stream = entry.get_object()
                if isinstance(stream, StreamObject) and STREAM_KEY in stream:
                    if str(stream[STREAM_KEY]) == "/Boxes":
                        taken += len(_MARK.findall(stream.get_data()))
                    continue
                kept.append(entry)
            if taken:
                # Our streams are gone; what is left is the page's own content, untouched.
                if kept:
                    page[NameObject("/Contents")] = ArrayObject(kept)
                else:
                    del page["/Contents"]
            elif any(
                isinstance(entry.get_object(), StreamObject)
                and _MARK.search(entry.get_object().get_data())
                for entry in entries
            ):
                # A tool has merged our streams with the page's: strip the blocks themselves.
                taken = _strip_marked_content(writer, page)
            removed += taken
        if not removed:
            raise ValueError("No Privacy Guardian redaction boxes were found in this file")
        output = io.BytesIO()
        writer.write(output)
        content = output.getvalue()
        if _pdf_marks(content):
            raise ValueError("The restored copy still carries redaction boxes")
        return RedactionResult(
            content=content,
            filename=f"{stem}-restored.pdf",
            mime="application/pdf",
            verified=True,
            boxes=removed,
        )
    if suffix == ".png" or data.startswith(b"\x89PNG"):
        from PIL import Image

        with Image.open(io.BytesIO(data)) as original:
            raw = getattr(original, "text", {}).get(PNG_MARK_KEY, "")
            image = original.convert("RGB")
        if not raw:
            raise ValueError("No Privacy Guardian redaction boxes were found in this file")
        boxes = json.loads(raw).get("boxes", [])
        for box in boxes:
            left, top, right, bottom = (int(value) for value in box["rect"])
            with Image.open(io.BytesIO(base64.b64decode(box["png"]))) as patch:
                image.paste(patch.convert("RGB"), (left, top))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return RedactionResult(
            content=output.getvalue(),
            filename=f"{stem}-restored.png",
            mime="image/png",
            verified=True,
            boxes=len(boxes),
        )
    raise ValueError("Only PDF and PNG files redacted by Privacy Guardian can be restored")


def redact_document(
    data: bytes,
    filename: str,
    document: ExtractedDocument,
    categories: set[DataCategory] | None = None,
    *,
    strip_metadata: bool = False,
    findings: list[Finding] | None = None,
) -> RedactionResult:
    """A copy of `data` with a black box over every personal detail.

    `findings` are what the analysis flagged and the card reported; every one of them
    is covered, on top of whatever a fresh look at the text turns up. A flagged detail
    that cannot be placed on the page refuses the copy rather than leaving it visible.
    """
    suffix = Path(filename).suffix.lower()
    warnings: list[str] = []
    boxes = 0
    unplaced = 0
    if suffix in IMAGE_SUFFIXES:
        if strip_metadata:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as original:
                image = original.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
            content = output.getvalue()
        else:
            content, boxes, unplaced = _redact_image(data, document, categories, findings)
        new_name, mime = "redacted-image.png", "image/png"
    elif suffix in TEXT_SUFFIXES:
        if document.partial:
            raise ValueError("Cannot certify redaction of an incompletely extracted document")
        sanitized = [redact_text(page.text, categories, use_ner=True) for page in document.pages]
        content = "\n\n".join(sanitized).encode("utf-8")
        new_name, mime = "redacted-document.txt", "text/plain"
    else:
        if document.partial:
            raise ValueError("Cannot certify redaction of an incompletely extracted document")
        if suffix != ".pdf" and not data.startswith(b"%PDF-"):
            raise ValueError("Only PDF, image and plain-text files can be given a redacted copy")
        content, boxes, unplaced = _redact_pdf(data, document, categories, findings)
        new_name, mime = "redacted-document.pdf", "application/pdf"
    if unplaced:
        raise ValueError("Some details could not be located on the page to be covered")
    if strip_metadata:
        # This action promises metadata removal, not removal of visible image contents.
        check = extract_document(content, new_name)
        verified = DataCategory.LOCATION_PRECISE not in check.metadata_categories
        warnings.append("Location metadata removed; visible image content is unchanged.")
    elif suffix in TEXT_SUFFIXES:
        check = extract_document(content, new_name)
        remaining = [
            finding
            for page in check.pages
            for finding in detect_pii(page.text, use_ner=True)
            if _wanted(finding.category, categories)
        ]
        verified = not remaining and not check.partial
    else:
        # The boxes are the redaction: every one drawn must be in the file, and any
        # match that had nowhere to be drawn has already refused the copy above.
        verified = redaction_marks(content, new_name) == boxes and (
            boxes > 0 or not document.pages or not any(page.text.strip() for page in document.pages)
        )
        warnings.append(
            "Black boxes cover the details. What is under them stays in the file, so the "
            "original can be restored from this copy later."
        )
    if not verified:
        raise ValueError("The redacted copy could not pass a complete verification scan")
    return RedactionResult(
        content=content,
        filename=new_name,
        mime=mime,
        verified=verified,
        warnings=warnings,
        boxes=boxes,
    )
