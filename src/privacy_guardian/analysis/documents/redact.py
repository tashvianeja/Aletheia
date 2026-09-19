from __future__ import annotations

import io
from pathlib import Path

from pydantic import BaseModel, Field

from privacy_guardian.analysis.documents.extract import ExtractedDocument, extract_document
from privacy_guardian.analysis.pii import detect_pii, find_matches, redact_text
from privacy_guardian.core.events import DataCategory


class RedactionResult(BaseModel):
    content: bytes = Field(repr=False)
    filename: str
    mime: str
    verified: bool
    warnings: list[str] = Field(default_factory=list)


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
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}:
        from PIL import Image, ImageDraw

        with Image.open(io.BytesIO(data)) as original:
            image = original.convert("RGB")
        drawing = ImageDraw.Draw(image)
        if not strip_metadata:
            if (
                DataCategory.BIOMETRIC_PHOTO in (categories or set())
                or document.document_type == "identity_document"
            ):
                drawing.rectangle((0, 0, image.width, image.height), fill="black")
            else:
                for page in document.pages:
                    for match in find_matches(page.text, use_ner=True):
                        if categories is not None and match.category not in categories:
                            continue
                        for start, end, left, top, width, height in page.boxes:
                            if match.start < end and match.end > start:
                                drawing.rectangle(
                                    (
                                        max(0, left - 2),
                                        max(0, top - 2),
                                        left + width + 2,
                                        top + height + 2,
                                    ),
                                    fill="black",
                                )
        output = io.BytesIO()
        # New encoder, no exif/icc/xmp parameters: metadata bytes are not copied.
        image.save(output, format="PNG")
        content = output.getvalue()
        new_name, mime = "redacted-image.png", "image/png"
    else:
        if document.partial:
            raise ValueError("Cannot certify redaction of an incompletely extracted document")
        sanitized = [redact_text(page.text, categories, use_ner=True) for page in document.pages]
        if suffix in {".txt", ".csv", ".json", ".md", ".log", ""}:
            content = "\n\n".join(sanitized).encode("utf-8")
            new_name, mime = "redacted-document.txt", "text/plain"
        else:
            # Rebuild, never overlay: no original streams, hidden text, images, attachments or metadata survive.
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen.canvas import Canvas

            output = io.BytesIO()
            canvas = Canvas(output, pagesize=A4, pageCompression=1)
            canvas.setTitle("Redacted document")
            canvas.setAuthor("")
            canvas.setSubject("")
            for text in sanitized:
                cursor = 800.0
                for line in text.splitlines():
                    chunks = [line[index : index + 95] for index in range(0, len(line), 95)] or [""]
                    for chunk in chunks:
                        if cursor < 40:
                            canvas.showPage()
                            cursor = 800.0
                        canvas.setFont("Helvetica", 10)
                        canvas.drawString(40, cursor, chunk)
                        cursor -= 14
                canvas.showPage()
            canvas.save()
            content = output.getvalue()
            new_name, mime = "redacted-document.pdf", "application/pdf"
            warnings.append(
                "The safe copy rebuilds text and removes original images, hidden content, and metadata; layout may change."
            )
    check = extract_document(content, new_name)
    remaining = [
        finding
        for page in check.pages
        for finding in detect_pii(page.text, use_ner=True)
        if categories is None or finding.category in categories
    ]
    meta_remaining = check.metadata_categories & (
        categories if categories is not None else set(DataCategory)
    )
    if strip_metadata:
        # This action promises metadata removal, not removal of visible image contents.
        verified = DataCategory.LOCATION_PRECISE not in check.metadata_categories
        warnings.append("Location metadata removed; visible image content is unchanged.")
    else:
        verified = not remaining and not meta_remaining and not check.partial
    if not verified:
        raise ValueError("The redacted copy could not pass a complete verification scan")
    return RedactionResult(
        content=content, filename=new_name, mime=mime, verified=verified, warnings=warnings
    )
