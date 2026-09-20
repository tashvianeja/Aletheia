from __future__ import annotations

import base64
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from aletheia.analysis.documents.extract import ExtractedDocument, extract_document
from aletheia.analysis.documents.masking import (
    Flagged,
    RedactionPlan,
    cover_ranges,
    plan_for,
    spans_to_cover,
)
from aletheia.analysis.documents.qr import find_qr_codes
from aletheia.analysis.pii import detect_pii, redact_text
from aletheia.core.events import DataCategory, Finding

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
MARK_TAG = "/Aletheia"
STREAM_KEY = "/PGRedaction"
PNG_MARK_KEY = "pg-redaction"
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"})
TEXT_SUFFIXES = frozenset({".txt", ".csv", ".json", ".md", ".log", ""})
# OCR runs on a page rendered at twice its natural size (extract.py, scale=2).
OCR_SCALE = 2.0
# Looking for codes means rendering the page, which an identity document of one or two
# pages can well afford. A long document that merely mentions a passport is classified
# the same way, so the search stops after this many pages and the copy says it did.
MAX_CODE_PAGES = 20
# How much of a picture the single commonest colour may cover before the picture is
# read as a drawing rather than a photograph. A logo, a banner, a rule between
# sections, a QR symbol and a block of printed text are all built out of areas of one
# flat colour; a photograph of a face has almost none of that. On a real Aadhaar the
# commonest colour in the portrait covers well under a hundredth of it, and in every
# other picture the card carries, two fifths or more.
FLAT_COLOUR_SHARE = 0.3
# The shape and size of a portrait on a page: about as tall as it is wide, and small
# enough to sit beside the text rather than behind it. A picture of that shape counts
# as a photograph whatever its colours, which is what catches a face shot against a
# plain backdrop that the colour test alone would read as flat.
PORTRAIT_ASPECT = (0.4, 1.2)
PORTRAIT_PAGE_SHARE = 0.08
Box = tuple[float, float, float, float]
Span = tuple[int, int]
# How deep a printed line runs on the page, top to bottom, or across when turned.
Band = tuple[float, float]
_MARK = re.compile(rb"/Aletheia\s*<<[^>]*>>\s*BDC")


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
) -> list[Flagged]:
    """The details the analysis flagged on this page, as offsets into its text."""
    spans: list[Flagged] = []
    for finding in findings or []:
        if finding.page not in (None, page) or not _wanted(finding.category, categories):
            continue
        start, _, end = finding.span_ref.partition(":")
        if start.isdigit() and end.isdigit() and int(end) > int(start):
            spans.append((int(start), int(end), finding.category))
    return spans


def _slice(box: Box, length: int, begin: int, end: int) -> Box:
    """The part of a word's box holding characters [begin, end) of it.

    Characters are taken to be evenly spaced across the word, which is what lets the
    first eight digits of a number be covered while its last four stay readable when
    a scan hands back all twelve as one token.
    """
    if length <= 0 or (begin <= 0 and end >= length):
        return box
    width = box[2] - box[0]
    return (
        box[0] + width * max(0, begin) / length,
        box[1],
        box[0] + width * min(length, end) / length,
        box[3],
    )


def _ocr_boxes(page: Any, spans: list[Span]) -> tuple[list[Box], int]:
    """Pixel boxes on an OCR'd page for each of `spans`.

    The boxes are measured on the page as a viewer shows it, so a token's characters
    always run along its box and part of one can be covered. Returns the boxes and
    how many spans had no token under them at all.
    """
    boxes: list[Box] = []
    unplaced = 0
    for start, end in spans:
        hits = [
            _slice(
                (left - 2, top - 2, left + width + 2, top + height + 2),
                token_end - token_start,
                start - token_start,
                end - token_start,
            )
            for token_start, token_end, left, top, width, height in page.boxes
            if start < token_end and end > token_start
        ]
        if not hits:
            unplaced += 1
        boxes.extend(hits)
    return boxes, unplaced


def _line_bands(words: list[Any], turned: bool) -> dict[int, Band]:
    """For each word, how deep the printed line it stands on runs, top to bottom.

    A bar the height of one word is not always a bar over the line it is printed on.
    An Aadhaar sets its punctuation and its Latin digits on a baseline of their own, a
    third of a line above the Indic script beside them, and a font that reports the
    height of a bare consonant reports nothing for the vowel marks drawn above it. A
    bar sized to one such word stops short of the marks on its neighbours and they
    read clearly over the top of it.

    So words are gathered into lines by whether their extents lie over one another —
    not by whether their tops agree, which is what splits a line set on two baselines
    into two — and every word on a line is given the whole line's depth. On a page
    shown turned by a quarter a line runs down the page, and its extent is across.
    """
    near, far = ("x0", "x1") if turned else ("top", "bottom")
    bands: dict[int, Band] = {}
    line: list[Any] = []
    band: Band = (0.0, 0.0)
    for word in [*words, None]:
        reach = (float(word[near]), float(word[far])) if word is not None else None
        shared = (
            min(reach[1], band[1]) - max(reach[0], band[0]) if line and reach is not None else -1.0
        )
        if (
            line
            and reach is not None
            and shared > 0.5 * min(reach[1] - reach[0], band[1] - band[0])
        ):
            line.append(word)
            band = (min(band[0], reach[0]), max(band[1], reach[1]))
            continue
        for member in line:
            bands[id(member)] = band
        if reach is None:
            break
        line, band = [word], reach
    return bands


def _compact(text: str) -> str:
    return "".join(text.split())


def _compact_range(value: str, begin: int, end: int) -> Span:
    """A range within `value` restated as a range within `value` with spaces removed."""
    start = len(_compact(value[:begin]))
    return start, start + len(_compact(value[begin:end]))


def _pdf_page_boxes(
    layout_page: Any,
    plan: RedactionPlan,
    categories: set[DataCategory] | None,
    flagged: list[tuple[str, DataCategory]],
    shown_height: float,
    turned: bool = False,
) -> tuple[list[Box], int]:
    """Boxes, in the page's displayed space, for the matches on a page with its own text.

    `flagged` are the strings the analysis flagged and the category it flagged each
    one under, found again here word by word and regardless of spacing, because the
    text the analysis read and the words the layout gives back are not laid out
    identically. `shown_height` is the height of the page as displayed: the layout
    measures a word's top from there, but reports the unrotated height as the page's,
    so a turned page cannot be trusted for it. Returns the boxes and how many values
    or matches could not be placed: one with no word under it is one the box cannot
    cover, and the copy is not certified.
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
    bands = _line_bands(words, turned)

    def rect(word: Any) -> Box:
        """A word's box, drawn as deep as the whole printed line it stands on."""
        low, high = bands[id(word)]
        if turned:
            return (
                low - 1.5,
                shown_height - float(word["bottom"]) - 1.5,
                high + 1.5,
                shown_height - float(word["top"]) + 1.5,
            )
        return (
            float(word["x0"]) - 1.5,
            shown_height - high - 1.5,
            float(word["x1"]) + 1.5,
            shown_height - low + 1.5,
        )

    # On a page shown turned, a word's own characters do not run along the box that
    # the layout reports for it, so part of one cannot be covered reliably; there the
    # whole word goes under the bar, which covers more rather than less.
    def bar(word: Any, length: int, begin: int, finish: int) -> Box:
        return _slice(rect(word), 0 if turned else length, begin, finish)

    boxes: list[Box] = []
    unplaced = 0
    for begin, finish in spans_to_cover(text, plan, categories):
        hits = [
            bar(word, end - start, begin - start, finish - start)
            for start, end, word in spans
            if begin < end and finish > start
        ]
        if not hits:
            unplaced += 1
        boxes.extend(hits)
    # Every word's characters, run together, with the word each character came from.
    joined = ""
    owner: list[int] = []
    for index, (_start, _end, word) in enumerate(spans):
        compact = _compact(str(word["text"]))
        joined += compact
        owner.extend([index] * len(compact))
    # Where each word's characters begin within that run-together text.
    starts: list[int] = []
    position = 0
    for _start, _end, word in spans:
        starts.append(position)
        position += len(_compact(str(word["text"])))
    for value, category in dict.fromkeys(flagged):
        ranges = [
            _compact_range(value, begin, finish)
            for begin, finish in cover_ranges(plan, category, value)
        ]
        needle = _compact(value)
        if not needle or not ranges:
            # Nothing to look for, or a detail this plan leaves readable on purpose.
            continue
        found = False
        at = joined.find(needle)
        while at >= 0:
            found = True
            for begin, finish in ranges:
                for index in sorted(set(owner[at + begin : at + finish])):
                    word = spans[index][2]
                    length = len(_compact(str(word["text"])))
                    boxes.append(
                        bar(word, length, at + begin - starts[index], at + finish - starts[index])
                    )
            at = joined.find(needle, at + 1)
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
    """How many Aletheia redaction boxes `data` carries, or 0 for none.

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


def _scheme_notes(plan: RedactionPlan, document: ExtractedDocument, codes: int) -> list[str]:
    """What the person needs to know about the rule this copy was made under.

    A plan that leaves details readable has to say which ones, or the copy looks more
    redacted than it is and gets shared somewhere it should not be.
    """
    notes: list[str] = []
    if plan.scheme == "aadhaar":
        notes.append(
            "Masked the way a shared Aadhaar should be: the first eight digits of the "
            "number, the Virtual ID, the QR code, the photograph, the address, the phone "
            "number, the email address and the exact date of birth are covered. The name, "
            "the gender, the year of birth and the last four digits stay readable, so the "
            "copy is still worth something to an identity check."
        )
        if not codes:
            notes.append(
                "No QR code could be found on this copy. An Aadhaar carries one, and it "
                "holds everything the card prints, so check the copy before sharing it."
            )
    elif plan.cover_pictures:
        notes.append(
            "Every detail found on this identity document is covered. Aletheia "
            "does not know this document's scheme, so it keeps nothing readable."
        )
    return notes


def _rendered_page(data: bytes, index: int) -> Any:
    """The page as a viewer shows it, at the scale the OCR boxes are measured in."""
    import pypdfium2

    with pypdfium2.PdfDocument(data) as raster:
        return raster[index].render(scale=OCR_SCALE).to_pil()


def _embedded_pictures(reader_page: Any) -> dict[str, Any]:
    """Every picture on a page, decoded, under the name its layout entry carries."""
    pictures: dict[str, Any] = {}
    try:
        entries = list(reader_page.images)
    except Exception:
        return pictures
    for entry in entries:
        try:
            pictures[Path(str(entry.name)).stem] = entry.image
        except Exception:
            continue
    return pictures


def _flat_colour_share(image: Any) -> float:
    """How much of a picture its single commonest colour covers.

    Measured on a sample of at most 128 by 128 pixels taken without interpolation, so
    that the colours counted are the picture's own rather than averages of them.
    """
    from PIL import Image

    sample = image.convert("RGB")
    sample = sample.resize(
        (min(128, sample.width), min(128, sample.height)), Image.Resampling.NEAREST
    )
    # Pillow 12 renamed this and deprecated the old name; the floor is Pillow 11.
    read = getattr(sample, "get_flattened_data", None) or sample.getdata
    pixels = list(read())
    if not pixels:
        return 1.0
    return max(Counter(pixels).values()) / len(pixels)


def _is_photograph(box: Box, image: Any | None, page_area: float) -> bool:
    """Whether a picture placed at `box` is a photograph of somebody.

    Either of two things says so, and either alone is enough, because the cost of
    getting it wrong is not symmetric: a logo under a black box is untidy, a face
    left showing is the biometric the copy was made to withhold. The first is the
    picture's own colours, which separate a photograph from a drawing. The second is
    its shape and size on the page: nothing else on an identity document is a small
    upright rectangle, and reading that shape as a portrait covers a face shot
    against a plain backdrop, which by colour alone looks like a drawing.
    """
    width, height = box[2] - box[0], box[3] - box[1]
    if width <= 0 or height <= 0:
        return False
    if image is None:
        # Nothing to look at. A picture that will not decode is covered rather than
        # trusted, because what is printed on it cannot be ruled out.
        return True
    low, high = PORTRAIT_ASPECT
    if low <= width / height <= high and width * height <= PORTRAIT_PAGE_SHARE * page_area:
        return True
    try:
        return _flat_colour_share(image) < FLAT_COLOUR_SHARE
    except (OSError, ValueError):
        return True


def _picture_boxes(layout_page: Any, reader_page: Any, shown_height: float) -> list[Box]:
    """Where the photographs embedded in a page are, in its displayed space.

    Only the photographs. A page's pictures also include its logos, its banners, the
    rules between its sections and, on an e-Aadhaar, the whole block of standing
    advice the issuer ships as an image rather than as text. Painting those out
    defaces the copy for the person receiving it while withholding nothing at all,
    and a copy that looks destroyed is one they send the original instead of.
    """
    pictures = _embedded_pictures(reader_page)
    page_area = max(1.0, float(layout_page.width) * float(layout_page.height))
    boxes = []
    for picture in layout_page.images:
        box = (
            float(picture["x0"]),
            shown_height - float(picture["bottom"]),
            float(picture["x1"]),
            shown_height - float(picture["top"]),
        )
        if _is_photograph(box, pictures.get(str(picture.get("name", ""))), page_area):
            boxes.append(box)
    return boxes


def _redact_pdf(
    data: bytes,
    document: ExtractedDocument,
    categories: set[DataCategory] | None,
    findings: list[Finding] | None,
) -> tuple[bytes, int, int, list[str]]:
    """Paint a box over every detail the plan covers, on the document as it is.

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
    plan = plan_for(document)
    by_number = {page.number: page for page in document.pages}
    drawn = 0
    unplaced = 0
    codes = 0
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
            crop = page.cropbox
            cropbox = (float(crop.left), float(crop.bottom), float(crop.right), float(crop.top))
            # A render covers the crop box; the layout measures against the whole page.
            render_height = cropbox[2] - cropbox[0] if turned else cropbox[3] - cropbox[1]
            layout_height = mediabox[2] - mediabox[0] if turned else mediabox[3] - mediabox[1]

            def from_pixels(
                pixels: list[Box],
                height: float = render_height,
                turn: int = rotation,
                box: Box = cropbox,
            ) -> list[Box]:
                """Pixel boxes on the render, mapped onto the page's own coordinates."""
                return [
                    _user_space(
                        (
                            left / OCR_SCALE,
                            height - bottom / OCR_SCALE,
                            right / OCR_SCALE,
                            height - top / OCR_SCALE,
                        ),
                        turn,
                        box,
                    )
                    for left, top, right, bottom in pixels
                ]

            boxes: list[Box] = []
            if extracted is not None and extracted.boxes:
                # A scanned page: the OCR token boxes are pixels on a render of the page
                # as displayed, at OCR_SCALE, measured from its top-left corner.
                pixel_boxes, missed = _ocr_boxes(
                    extracted, spans_to_cover(extracted.text, plan, categories, flagged)
                )
                unplaced += missed
                boxes = from_pixels(pixel_boxes)
            elif index < len(layout.pages):
                values = (
                    [(extracted.text[start:end], category) for start, end, category in flagged]
                    if extracted is not None
                    else []
                )
                shown_boxes, missed = _pdf_page_boxes(
                    layout.pages[index], plan, categories, values, layout_height, turned
                )
                unplaced += missed
                boxes = [_user_space(box, rotation, mediabox) for box in shown_boxes]
            if plan.cover_codes and index < MAX_CODE_PAGES:
                found = from_pixels(find_qr_codes(_rendered_page(data, index)))
                codes += len(found)
                boxes.extend(found)
            if plan.cover_pictures and index < len(layout.pages):
                boxes.extend(
                    _user_space(box, rotation, mediabox)
                    for box in _picture_boxes(layout.pages[index], page, layout_height)
                )
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
    notes = _scheme_notes(plan, document, codes)
    if plan.cover_codes and len(writer.pages) > MAX_CODE_PAGES:
        notes.append(
            f"Codes were looked for on the first {MAX_CODE_PAGES} pages only; any QR "
            "code further in is not covered."
        )
    return output.getvalue(), drawn, unplaced, notes


def _redact_image(
    data: bytes,
    document: ExtractedDocument,
    categories: set[DataCategory] | None,
    findings: list[Finding] | None,
) -> tuple[bytes, int, int, list[str]]:
    """Paint the boxes onto the pixels, keeping what they covered inside the file."""
    from PIL import Image, ImageDraw
    from PIL.PngImagePlugin import PngInfo

    with Image.open(io.BytesIO(data)) as original:
        image = original.convert("RGB")
    plan = plan_for(document)
    boxes: list[Box] = []
    unplaced = 0
    for page in document.pages:
        found, missed = _ocr_boxes(
            page,
            spans_to_cover(
                page.text, plan, categories, _flagged_spans(findings, page.number, categories)
            ),
        )
        boxes.extend(found)
        unplaced += missed
    codes = 0
    if plan.cover_codes:
        found_codes = find_qr_codes(image)
        codes = len(found_codes)
        boxes.extend(found_codes)
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
    notes = _scheme_notes(plan, document, codes)
    if plan.cover_pictures:
        # A flat scan has no picture the file marks out as one, so unlike a PDF there
        # is nothing here to put a box over. Say so rather than imply the face is gone.
        notes.append(
            "One thing above is not true of this copy: the photograph is still visible. "
            "This file is a scan, a single flat picture of the page, and it gives nothing "
            "to tell the portrait on it from everything printed around it. Share the PDF "
            "of this document instead if the photograph has to come off."
        )
    return output.getvalue(), len(covered), unplaced, notes


def unredact_document(data: bytes, filename: str) -> RedactionResult:
    """Take Aletheia's boxes off a file it redacted, leaving all else as is."""
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
            raise ValueError("No Aletheia redaction boxes were found in this file")
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
            raise ValueError("No Aletheia redaction boxes were found in this file")
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
    raise ValueError("Only PDF and PNG files redacted by Aletheia can be restored")


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
    identity = document.document_type == "identity_document"
    if suffix in IMAGE_SUFFIXES:
        if strip_metadata:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as original:
                image = original.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
            content = output.getvalue()
        else:
            if identity and document.partial:
                # Half-read text on an ID is where the number goes uncovered.
                raise ValueError("Cannot certify redaction of an incompletely read document")
            content, boxes, unplaced, notes = _redact_image(data, document, categories, findings)
            warnings.extend(notes)
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
        content, boxes, unplaced, notes = _redact_pdf(data, document, categories, findings)
        warnings.extend(notes)
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
        # An identity document with nothing covered is not a redacted copy, whatever
        # the extraction made of it; anything else may legitimately have nothing on it.
        verified = redaction_marks(content, new_name) == boxes and (
            boxes > 0
            or (
                not identity
                and (not document.pages or not any(page.text.strip() for page in document.pages))
            )
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
