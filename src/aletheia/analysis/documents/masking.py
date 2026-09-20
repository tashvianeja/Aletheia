"""What to cover on a document, and what has to stay readable.

A redacted identity document is only worth making if it still works as an identity
document. Painting the whole card black removes every detail on it, including the
ones the person is sharing it to prove, and what they get back is a file nobody can
accept — so they send the original instead and the redaction has achieved nothing.

What to cover is therefore a question about the kind of document, not about the fact
that it is one. UIDAI answers half of it for Aadhaar itself: a Masked Aadhaar hides
the first eight digits of the number and leaves the last four, which is the form
every Indian counter already accepts. The name, the gender and the year of birth go
with it, because those are what an identity check reads.

Everything else on the card comes off. The number in full, the Virtual ID, the exact
date of birth, the address, the phone number and the email address are what turn a
shared copy into something that can be used to impersonate somebody. So is the QR
code, which holds all of it again in a form a phone reads in a second, and so is the
photograph: a face is matched against a face, and no form asking for an Aadhaar is
checking one. This module holds that rule, and the cautious default for an ID whose
scheme is not recognised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aletheia.analysis.pii import find_matches
from aletheia.core.events import DataCategory

if TYPE_CHECKING:
    from aletheia.analysis.documents.extract import ExtractedDocument

Span = tuple[int, int]
Flagged = tuple[int, int, DataCategory]


@dataclass(frozen=True)
class RedactionPlan:
    """The rule a single document is redacted under."""

    scheme: str = ""
    # Detected on the page, and deliberately left readable.
    keep: frozenset[DataCategory] = frozenset()
    # Categories only part of whose value is covered, and which part survives.
    partial: dict[DataCategory, str] = field(default_factory=dict)
    # Look for QR and similar codes and cover them: they carry, in a form a phone
    # reads in a second, everything the printed side of the document says.
    cover_codes: bool = False
    # Cover the photographs embedded in the page. On an ID that is the portrait of
    # the holder, which is a biometric: a face is matched against a face, and a copy
    # that carries one hands over the means of that match to whoever holds the copy.
    cover_pictures: bool = False

    def covers(self, category: DataCategory) -> bool:
        return category not in self.keep


_AADHAAR = RedactionPlan(
    scheme="aadhaar",
    # Name, gender and age are what an Aadhaar is shown to prove, and a copy that
    # covers them is useless for the check the person is sharing it for. The
    # photograph is not in that list: a face is the one detail on the card that is
    # matched automatically, against a photograph taken somewhere else, and it is
    # never what a form asking for an Aadhaar is checking.
    keep=frozenset({DataCategory.FULL_NAME, DataCategory.GENDER, DataCategory.AGE}),
    partial={DataCategory.GOVERNMENT_ID_NATIONAL_ID: "aadhaar", DataCategory.DOB: "year"},
    cover_codes=True,
    cover_pictures=True,
)
# Any other identity document: cover everything found on it, including the portrait
# and any code, because nothing here knows which of its details the holder needs to
# keep provable.
_IDENTITY = RedactionPlan(scheme="", cover_codes=True, cover_pictures=True)
_PLAIN = RedactionPlan()


def plan_for(document: ExtractedDocument) -> RedactionPlan:
    if document.document_type != "identity_document":
        return _PLAIN
    if document.id_scheme == "aadhaar":
        return _AADHAAR
    return _IDENTITY


def _mask_aadhaar(value: str) -> list[Span]:
    """Cover an Aadhaar number down to its last four digits, or a VID completely.

    Both are printed on the card and both are national-ID numbers, but only the
    twelve-digit Aadhaar has a masked form anybody accepts. A Virtual ID is a
    revocable stand-in that nothing is checked against four digits at a time, so
    leaving part of one showing gives up information and buys nothing.
    """
    if len(re.sub(r"\D", "", value)) != 12:
        return [(0, len(value))]
    return _keep_last_digits(value, 4)


def _keep_last_digits(value: str, keep: int) -> list[Span]:
    """Cover all of `value` but its last `keep` digits, the way a masked ID reads."""
    seen = 0
    for index in range(len(value) - 1, -1, -1):
        if value[index].isdigit():
            seen += 1
            if seen == keep:
                return [(0, index)] if index > 0 else []
    # Fewer digits than the mask would leave showing: cover the lot.
    return [(0, len(value))]


def _keep_year(value: str) -> list[Span]:
    """Cover a date down to its year, which is all an age check needs."""
    year = re.search(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)", value)
    if year is None:
        return [(0, len(value))]
    return [
        span
        for span in ((0, year.start()), (year.end(), len(value)))
        if span[1] > span[0] and value[span[0] : span[1]].strip(" -/.,")
    ]


def cover_ranges(plan: RedactionPlan, category: DataCategory, value: str) -> list[Span]:
    """Which parts of one detected value get a box, as offsets into it.

    Usually the whole of it. An empty list means the plan leaves this one readable.
    """
    if not plan.covers(category):
        return []
    rule = plan.partial.get(category)
    if rule == "aadhaar":
        return _mask_aadhaar(value)
    if rule == "year":
        return _keep_year(value)
    return [(0, len(value))]


# A six-digit PIN, which is what an Indian address ends on.
_PIN = re.compile(r"(?<!\d)\d{6}(?!\d)")
# A line that stops an address block being walked back any further, because what it
# holds is the last thing above the address that an Aadhaar keeps readable: the
# gender, the date of birth, the printed number in whichever form the card shows it,
# or the care-of line naming a parent.
_ABOVE_THE_ADDRESS = re.compile(
    r"\b(?:male|female|transgender|dob|d\.o\.b|born|year\s+of\s+birth)\b"
    r"|पुरुष|महिला|जन्म"
    r"|(?<![\dX*])[\dX*]{4}\s*[\dX*]{4}\s*[\dX*]{4}(?![\dX*])"
    r"|\b[CSDW]/O\b",
    re.I,
)
# How far back that walk may go. An Aadhaar prints the address twice, once in English
# and once in the holder's own language, and a layout reader breaks the second onto a
# line per comma, so the run is a good deal longer than it looks on the page.
MAX_BLOCK_LINES = 40


def _line_bounds(text: str) -> list[Span]:
    bounds: list[Span] = []
    start = 0
    for line in text.split("\n"):
        bounds.append((start, start + len(line)))
        start += len(line) + 1
    return bounds


def _address_blocks(text: str, covered: list[Span], kept: list[Span]) -> list[Span]:
    """An address found by its shape, for the copy of it that cannot be read at all.

    An Aadhaar prints its address twice: once in English, and once in the language the
    card was issued in. The second copy is routinely beyond reading — the fonts an
    e-Aadhaar embeds hand back nothing usable for most Indic scripts, so neither the
    word above the block nor anything inside it can be matched, though every one of
    it is perfectly legible to whoever opens the file. Leaving it showing redacts the
    address for a Hindi cardholder and nobody else.

    What survives the encoding is the block's shape. It ends on the six-digit PIN, and
    it begins after the last line carrying something the card keeps readable, which on
    every Aadhaar layout is what sits directly above it. Only a PIN that nothing has
    covered yet starts a walk, so the blocks found by their labels keep those labels
    readable and this applies to the copy that has none.
    """
    bounds = _line_bounds(text)
    blocks: list[Span] = []
    for index, (start, end) in enumerate(bounds):
        pins = list(_PIN.finditer(text, start, end))
        if not pins:
            continue
        pin = pins[-1]
        if any(span[0] <= pin.start() and pin.end() <= span[1] for span in covered):
            continue
        first = index
        for step in range(1, min(MAX_BLOCK_LINES, index) + 1):
            above = bounds[index - step]
            if _ABOVE_THE_ADDRESS.search(text[above[0] : above[1]]) or any(
                span[0] < above[1] and above[0] < span[1] for span in kept
            ):
                break
            first = index - step
        if first < index:
            blocks.append((bounds[first][0], pin.end()))
    return blocks


def spans_to_cover(
    text: str,
    plan: RedactionPlan,
    categories: set[DataCategory] | None,
    flagged: list[Flagged] | None = None,
) -> list[Span]:
    """Every span of `text` that gets a box: what a fresh look finds, plus `flagged`.

    `flagged` is what the analysis reported to the person on the card, carried through
    so the copy covers exactly what they were told about. Both go through the plan, so
    a detail the scheme keeps readable stays readable however it was found.
    """
    found: list[Flagged] = [
        (match.start, match.end, match.category)
        for match in find_matches(text, use_ner=True)
        if categories is None or match.category in categories
    ]
    found.extend(
        (start, end, category)
        for start, end, category in flagged or []
        if categories is None or category in categories
    )
    spans: list[Span] = []
    for start, end, category in found:
        spans.extend(
            (start + begin, start + finish)
            for begin, finish in cover_ranges(plan, category, text[start:end])
        )
    if plan.scheme == "aadhaar" and (
        categories is None or DataCategory.POSTAL_ADDRESS in categories
    ):
        kept = [(start, end) for start, end, category in found if not plan.covers(category)]
        spans.extend(_address_blocks(text, spans, kept))
    return list(dict.fromkeys(spans))
