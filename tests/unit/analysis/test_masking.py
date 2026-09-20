from __future__ import annotations

import pytest

from privacy_guardian.analysis.documents.extract import ExtractedDocument
from privacy_guardian.analysis.documents.masking import cover_ranges, plan_for, spans_to_cover
from privacy_guardian.analysis.documents.qr import find_qr_codes
from privacy_guardian.core.events import DataCategory


def _document(kind: str = "identity_document", scheme: str = "") -> ExtractedDocument:
    return ExtractedDocument(document_type=kind, id_scheme=scheme)


def test_an_aadhaar_keeps_what_an_identity_check_reads_and_covers_the_rest() -> None:
    plan = plan_for(_document(scheme="aadhaar"))
    assert plan.scheme == "aadhaar"
    for kept in (DataCategory.FULL_NAME, DataCategory.GENDER, DataCategory.BIOMETRIC_PHOTO):
        assert not plan.covers(kept)
    for covered in (
        DataCategory.GOVERNMENT_ID_NATIONAL_ID,
        DataCategory.POSTAL_ADDRESS,
        DataCategory.PHONE,
        DataCategory.EMAIL,
        DataCategory.DOB,
    ):
        assert plan.covers(covered)
    assert plan.cover_codes
    # The face is what the card is shown to prove, so it is not painted over.
    assert not plan.cover_pictures


def test_an_identity_document_of_an_unknown_scheme_keeps_nothing_readable() -> None:
    plan = plan_for(_document())
    assert plan.covers(DataCategory.FULL_NAME)
    assert plan.cover_codes and plan.cover_pictures
    assert cover_ranges(plan, DataCategory.GOVERNMENT_ID_NATIONAL_ID, "2345 6789 0124") == [(0, 14)]


def test_an_ordinary_document_is_not_put_through_an_identity_rule() -> None:
    plan = plan_for(_document(kind="bank_statement"))
    assert not plan.cover_codes and not plan.cover_pictures
    assert cover_ranges(plan, DataCategory.DOB, "29/02/1988") == [(0, 10)]


@pytest.mark.parametrize(
    ("number", "covered"),
    [
        ("2345 6789 0124", "2345 6789 "),
        ("234567890124", "23456789"),
        ("2345-6789-0124", "2345-6789-"),
    ],
)
def test_an_aadhaar_number_loses_all_but_its_last_four_digits(number: str, covered: str) -> None:
    """What UIDAI's own Masked Aadhaar does, whatever spacing the card used."""
    plan = plan_for(_document(scheme="aadhaar"))
    [(start, end)] = cover_ranges(plan, DataCategory.GOVERNMENT_ID_NATIONAL_ID, number)
    assert number[start:end] == covered
    assert number[end:] == "0124"


def test_a_virtual_id_is_covered_whole_because_a_partial_one_proves_nothing() -> None:
    plan = plan_for(_document(scheme="aadhaar"))
    vid = "9012 3456 7890 1235"
    assert cover_ranges(plan, DataCategory.GOVERNMENT_ID_NATIONAL_ID, vid) == [(0, len(vid))]


@pytest.mark.parametrize("date", ["29/02/1988", "1988-02-29", "29 February 1988"])
def test_a_date_of_birth_comes_down_to_its_year(date: str) -> None:
    plan = plan_for(_document(scheme="aadhaar"))
    kept = date
    for start, end in sorted(cover_ranges(plan, DataCategory.DOB, date), reverse=True):
        kept = kept[:start] + kept[end:]
    assert kept.strip() == "1988"


def test_a_date_with_no_year_in_it_is_covered_entirely() -> None:
    plan = plan_for(_document(scheme="aadhaar"))
    assert cover_ranges(plan, DataCategory.DOB, "29/02") == [(0, 5)]


def test_the_spans_to_cover_carry_both_a_fresh_look_and_what_was_flagged() -> None:
    text = "Aadhaar 2345 6789 0124 for Morgan Testperson, reference AB-9931."
    plan = plan_for(_document(scheme="aadhaar"))
    at = text.index("AB-9931")
    flagged = [(at, at + len("AB-9931"), DataCategory.GOVERNMENT_ID_DRIVERS_LICENSE)]
    spans = spans_to_cover(text, plan, None, flagged)
    covered = {text[start:end] for start, end in spans}
    # The flagged detail is covered even though a fresh look does not see one there.
    assert "AB-9931" in covered
    # The number is masked, and the name the plan keeps is not in the list at all.
    assert any(value.startswith("2345 6789") and not value.endswith("0124") for value in covered)
    assert "Morgan Testperson" not in covered


def test_a_category_filter_still_narrows_what_gets_a_box() -> None:
    text = "Aadhaar 2345 6789 0124, email morgan.testperson@example.test"
    plan = plan_for(_document(scheme="aadhaar"))
    spans = spans_to_cover(text, plan, {DataCategory.EMAIL})
    assert {text[start:end] for start, end in spans} == {"morgan.testperson@example.test"}


def _qr_image(modules: int = 29, scale: int = 5, margin: int = 20) -> object:
    """A QR-shaped symbol drawn on a page, the way one sits on a card."""
    import random

    from PIL import Image, ImageDraw

    rng = random.Random(3)
    grid = [[rng.randint(0, 1) for _ in range(modules)] for _ in range(modules)]

    def finder(row: int, column: int) -> None:
        for down in range(-1, 8):
            for across in range(-1, 8):
                y, x = row + down, column + across
                if not (0 <= y < modules and 0 <= x < modules):
                    continue
                if down in (-1, 7) or across in (-1, 7):
                    grid[y][x] = 0
                elif down in (0, 6) or across in (0, 6) or (2 <= down <= 4 and 2 <= across <= 4):
                    grid[y][x] = 1
                else:
                    grid[y][x] = 0

    finder(0, 0)
    finder(0, modules - 7)
    finder(modules - 7, 0)
    side = modules * scale
    image = Image.new("RGB", (side + 2 * margin, side + 2 * margin), "white")
    draw = ImageDraw.Draw(image)
    for row in range(modules):
        for column in range(modules):
            if grid[row][column]:
                draw.rectangle(
                    (
                        margin + column * scale,
                        margin + row * scale,
                        margin + column * scale + scale - 1,
                        margin + row * scale + scale - 1,
                    ),
                    fill="black",
                )
    return image


def test_a_qr_code_is_located_by_its_finder_patterns_alone() -> None:
    """Nothing decodes the symbol; three corners of the right shape fix its square."""
    modules, scale, margin = 29, 5, 20
    [(x0, y0, x1, y1)] = find_qr_codes(_qr_image(modules, scale, margin))
    # The box lands on the symbol, give or take a module at each edge.
    assert abs(x0 - margin) <= scale and abs(y0 - margin) <= scale
    assert abs(x1 - (margin + modules * scale)) <= scale
    assert abs(y1 - (margin + modules * scale)) <= scale


def test_a_page_of_ordinary_text_is_not_mistaken_for_a_code() -> None:
    from PIL import Image, ImageDraw

    page = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(page)
    for line in range(12):
        draw.text((30, 30 + line * 24), "Quarterly notes for the team, page two", fill="black")
    assert find_qr_codes(page) == []
    assert find_qr_codes(Image.new("RGB", (300, 200), "white")) == []


def test_a_page_that_cannot_be_read_reports_no_codes_rather_than_failing() -> None:
    assert find_qr_codes(object()) == []
