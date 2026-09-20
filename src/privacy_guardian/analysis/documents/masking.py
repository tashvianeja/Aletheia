"""What to cover on a document, and what has to stay readable.

A redacted identity document is only worth making if it still works as an identity
document. Painting the whole card black removes every detail on it, including the
ones the person is sharing it to prove, and what they get back is a file nobody can
accept — so they send the original instead and the redaction has achieved nothing.

What to cover is therefore a question about the kind of document, not about the fact
that it is one. UIDAI answers it for Aadhaar itself: a Masked Aadhaar hides the first
eight digits of the number and leaves the last four, and leaves the name, the
photograph, the gender and the year of birth, because those are what an identity
check reads. The number in full, the Virtual ID, the QR code, the exact date of
birth, the address and any phone number or email printed on the card are what turn a
shared copy into something that can be used to impersonate somebody, and those come
off. This module holds that rule, and the cautious default for an ID whose scheme is
not recognised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from privacy_guardian.analysis.pii import find_matches
from privacy_guardian.core.events import DataCategory

if TYPE_CHECKING:
    from privacy_guardian.analysis.documents.extract import ExtractedDocument

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
    # Cover the pictures embedded in the page. On an ID that is the portrait, which
    # comes off unless the scheme says the face is part of what is being proved.
    cover_pictures: bool = False

    def covers(self, category: DataCategory) -> bool:
        return category not in self.keep


_AADHAAR = RedactionPlan(
    scheme="aadhaar",
    # Name, photograph, gender and age are what an Aadhaar is shown to prove. UIDAI's
    # own Masked Aadhaar leaves all four, and covering them is what makes a copy
    # useless for the check the person is sharing it for.
    keep=frozenset(
        {
            DataCategory.FULL_NAME,
            DataCategory.GENDER,
            DataCategory.AGE,
            DataCategory.BIOMETRIC_PHOTO,
        }
    ),
    partial={DataCategory.GOVERNMENT_ID_NATIONAL_ID: "aadhaar", DataCategory.DOB: "year"},
    cover_codes=True,
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
    return list(dict.fromkeys(spans))
