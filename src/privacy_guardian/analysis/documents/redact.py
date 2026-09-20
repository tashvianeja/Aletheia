from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from privacy_guardian.analysis.documents.extract import ExtractedDocument, extract_document
from privacy_guardian.analysis.pii import detect_pii, find_matches, redact_text
from privacy_guardian.core.events import DataCategory

# How a redaction box announces itself inside the file it was drawn on, so the same
# file can be recognised later and the box taken off again. In a PDF the box is a
# Square annotation carrying these two standard fields; in a PNG the covered pixels
# ride along in a text chunk under this key. Both survive a re-save or a compressor
# that keeps annotations and text chunks, which is what makes a restored copy of a
# compressed file possible.
MARK_AUTHOR = "Privacy Guardian"
MARK_SUBJECT = "Redaction"
PNG_MARK_KEY = "pg-redaction"
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"})
TEXT_SUFFIXES = frozenset({".txt", ".csv", ".json", ".md", ".log", ""})
# OCR runs on a page rendered at twice its natural size (extract.py, scale=2).
OCR_SCALE = 2.0
Box = tuple[float, float, float, float]


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


def _ocr_boxes(page: Any, categories: set[DataCategory] | None) -> list[Box]:
    """Pixel boxes for every detected match on an OCR'd page, from its token boxes."""
    boxes: list[Box] = []
    for match in find_matches(page.text, use_ner=True):
        if not _wanted(match.category, categories):
            continue
        for start, end, left, top, width, height in page.boxes:
            if match.start < end and match.end > start:
                boxes.append((left - 2, top - 2, left + width + 2, top + height + 2))
    return boxes


def _pdf_page_boxes(
    layout_page: Any, categories: set[DataCategory] | None
) -> tuple[list[Box], int]:
    """Boxes in PDF user space for the matches on a page that carries its own text.

    Returns the boxes and how many matches could not be placed: a match with no
    word under it is one the box cannot cover, and the copy is not certified.
    """
    words = layout_page.extract_words(keep_blank_chars=False, use_text_flow=True)
    text = ""
    spans: list[tuple[int, int, Any]] = []
    previous_top: float | None = None
    for word in words:
        if text:
            text += (
                " " if previous_top is not None and abs(word["top"] - previous_top) < 3 else "\n"
            )
        start = len(text)
        text += str(word["text"])
        spans.append((start, len(text), word))
        previous_top = float(word["top"])
    height = float(layout_page.height)
    boxes: list[Box] = []
    unplaced = 0
    for match in find_matches(text, use_ner=True):
        if not _wanted(match.category, categories):
            continue
        hits = [word for start, end, word in spans if match.start < end and match.end > start]
        if not hits:
            unplaced += 1
            continue
        for word in hits:
            boxes.append(
                (
                    float(word["x0"]) - 1.5,
                    height - float(word["bottom"]) - 1.5,
                    float(word["x1"]) + 1.5,
                    height - float(word["top"]) + 1.5,
                )
            )
    return boxes, unplaced


def _merge(boxes: list[Box]) -> list[Box]:
    """Fuse boxes that touch on one line, so a name is one bar rather than two."""
    merged: list[Box] = []
    for box in sorted(boxes, key=lambda item: (round(item[1]), item[0])):
        if merged:
            last = merged[-1]
            if abs(last[1] - box[1]) < 2 and abs(last[3] - box[3]) < 2 and box[0] - last[2] < 6:
                merged[-1] = (
                    last[0],
                    min(last[1], box[1]),
                    max(last[2], box[2]),
                    max(last[3], box[3]),
                )
                continue
        merged.append(box)
    return merged


def _square_annotation(box: Box, name: str) -> Any:
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
        StreamObject,
        TextStringObject,
    )

    x0, y0, x1, y1 = box
    rect = ArrayObject([FloatObject(x0), FloatObject(y0), FloatObject(x1), FloatObject(y1)])
    # An appearance stream of our own, so every viewer paints the same solid bar
    # instead of interpreting the annotation's colours its own way.
    appearance = StreamObject()
    appearance[NameObject("/Type")] = NameObject("/XObject")
    appearance[NameObject("/Subtype")] = NameObject("/Form")
    appearance[NameObject("/BBox")] = rect
    appearance.set_data(f"0 g {x0:.2f} {y0:.2f} {x1 - x0:.2f} {y1 - y0:.2f} re f".encode())
    normal = DictionaryObject({NameObject("/N"): appearance})
    black = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)])
    return DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Square"),
            NameObject("/Rect"): rect,
            NameObject("/C"): black,
            NameObject("/IC"): black,
            NameObject("/CA"): NumberObject(1),
            NameObject("/F"): NumberObject(4),
            NameObject("/T"): TextStringObject(MARK_AUTHOR),
            NameObject("/Subj"): TextStringObject(MARK_SUBJECT),
            NameObject("/NM"): TextStringObject(name),
            NameObject("/Contents"): TextStringObject("Covered by Privacy Guardian"),
            NameObject("/AP"): normal,
        }
    )


def _is_mark(annotation: Any) -> bool:
    try:
        return (
            str(annotation.get("/Subtype", "")) == "/Square"
            and str(annotation.get("/T", "")) == MARK_AUTHOR
            and str(annotation.get("/Subj", "")) == MARK_SUBJECT
        )
    except Exception:
        return False


def _pdf_marks(data: bytes) -> int:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        return 0
    count = 0
    for page in reader.pages:
        for annotation in page.get("/Annots") or []:
            if _is_mark(annotation.get_object()):
                count += 1
    return count


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
    data: bytes, document: ExtractedDocument, categories: set[DataCategory] | None
) -> tuple[bytes, int, int]:
    """Draw a box over every match, on the document as it is.

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
            box = page.mediabox
            width, height = float(box.width), float(box.height)
            boxes: list[Box]
            if cover_whole:
                boxes = [(float(box.left), float(box.bottom), float(box.right), float(box.top))]
            elif extracted is not None and extracted.boxes:
                # A scanned page: the OCR token boxes are pixels on a render at OCR_SCALE.
                boxes = [
                    (
                        float(box.left) + left / OCR_SCALE,
                        float(box.top) - bottom / OCR_SCALE,
                        float(box.left) + right / OCR_SCALE,
                        float(box.top) - top / OCR_SCALE,
                    )
                    for left, top, right, bottom in _ocr_boxes(extracted, categories)
                ]
            elif index < len(layout.pages):
                boxes, missed = _pdf_page_boxes(layout.pages[index], categories)
                unplaced += missed
                boxes = [
                    (
                        float(box.left) + x0,
                        float(box.bottom) + y0,
                        float(box.left) + x1,
                        float(box.bottom) + y1,
                    )
                    for x0, y0, x1, y1 in boxes
                ]
            else:
                boxes = []
            for x0, y0, x1, y1 in _merge(boxes):
                clipped = (
                    max(float(box.left), x0),
                    max(float(box.bottom), y0),
                    min(float(box.right), x1),
                    min(float(box.top), y1),
                )
                if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
                    continue
                drawn += 1
                writer.add_annotation(index, _square_annotation(clipped, f"pg-redaction-{drawn}"))
            del width, height
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue(), drawn, unplaced


def _redact_image(
    data: bytes, document: ExtractedDocument, categories: set[DataCategory] | None
) -> tuple[bytes, int]:
    """Paint the boxes onto the pixels, keeping what they covered inside the file."""
    from PIL import Image, ImageDraw
    from PIL.PngImagePlugin import PngInfo

    with Image.open(io.BytesIO(data)) as original:
        image = original.convert("RGB")
    boxes: list[Box]
    if (
        DataCategory.BIOMETRIC_PHOTO in (categories or set())
        or document.document_type == "identity_document"
    ):
        boxes = [(0, 0, image.width, image.height)]
    else:
        boxes = [box for page in document.pages for box in _ocr_boxes(page, categories)]
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
    return output.getvalue(), len(covered)


def unredact_document(data: bytes, filename: str) -> RedactionResult:
    """Take Privacy Guardian's boxes off a file it redacted, leaving all else as is."""
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem or "document"
    if suffix == ".pdf" or data.startswith(b"%PDF-"):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, NameObject

        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("Encrypted document requires a password")
        writer = PdfWriter(clone_from=reader)
        removed = 0
        for page in writer.pages:
            annotations = page.get("/Annots")
            if not annotations:
                continue
            kept = ArrayObject()
            for annotation in annotations:
                if _is_mark(annotation.get_object()):
                    removed += 1
                else:
                    kept.append(annotation)
            page[NameObject("/Annots")] = kept
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
) -> RedactionResult:
    suffix = Path(filename).suffix.lower()
    warnings: list[str] = []
    boxes = 0
    if suffix in IMAGE_SUFFIXES:
        if strip_metadata:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as original:
                image = original.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
            content = output.getvalue()
        else:
            content, boxes = _redact_image(data, document, categories)
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
        content, boxes, unplaced = _redact_pdf(data, document, categories)
        if unplaced:
            raise ValueError("Some details could not be located on the page to be covered")
        new_name, mime = "redacted-document.pdf", "application/pdf"
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
