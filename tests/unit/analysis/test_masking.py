from __future__ import annotations

import pytest

from aletheia.analysis.documents.extract import ExtractedDocument
from aletheia.analysis.documents.masking import cover_ranges, plan_for, spans_to_cover
from aletheia.analysis.documents.qr import find_qr_codes
from aletheia.core.events import DataCategory


def _document(kind: str = "identity_document", scheme: str = "") -> ExtractedDocument:
    return ExtractedDocument(document_type=kind, id_scheme=scheme)


def test_an_aadhaar_keeps_what_an_identity_check_reads_and_covers_the_rest() -> None:
    plan = plan_for(_document(scheme="aadhaar"))
    assert plan.scheme == "aadhaar"
    for kept in (DataCategory.FULL_NAME, DataCategory.GENDER, DataCategory.AGE):
        assert not plan.covers(kept)
    for covered in (
        DataCategory.GOVERNMENT_ID_NATIONAL_ID,
        DataCategory.POSTAL_ADDRESS,
        DataCategory.PHONE,
        DataCategory.EMAIL,
        DataCategory.DOB,
        DataCategory.BIOMETRIC_PHOTO,
    ):
        assert plan.covers(covered)
    # The code holds the whole record over again, and the face is a biometric that
    # nothing asking for an Aadhaar is checking. Both come off.
    assert plan.cover_codes and plan.cover_pictures


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


# The address column of an e-Aadhaar, set the way UIDAI sets it: a care-of line, then
# house and street with no label of their own, then one labelled field to a line.
_ADDRESS_COLUMN = """To
Basant Raj
C/O: Ramesh Raj
Flat 9, Nehru Apartments
Station Road
VTC: Sikandarpur
PO: Bhagwanpur
Sub District: Hajipur
District: Vaishali
State: Bihar
PIN Code: 844101
Mobile: 9835412876
आपका आधार क्रमांक / Your Aadhaar No. :
2345 6789 0124
"""


def _covered(text: str, scheme: str = "aadhaar") -> set[str]:
    plan = plan_for(_document(scheme=scheme))
    return {text[start:end] for start, end in spans_to_cover(text, plan, None)}


def test_the_address_column_of_an_aadhaar_is_covered_field_by_field() -> None:
    """UIDAI does not print the address under the word "address" — it prints a column.

    Nothing that looks for the word finds an Indian address at all, which left every
    line of one readable on a copy the person had been told was redacted.
    """
    covered = _covered(_ADDRESS_COLUMN)
    for value in ("Sikandarpur", "Bhagwanpur", "Hajipur", "Vaishali", "Bihar", "844101"):
        assert value in covered, value
    # The labels stay, so the copy still reads as an address that has been withheld
    # rather than as a card with a hole in it.
    assert not any(value.startswith(("VTC", "PIN", "State")) for value in covered)


def test_the_house_and_street_lines_are_covered_and_the_care_of_name_is_not() -> None:
    """The lines above the labelled fields carry no label, and are the street address.

    They are found from the care-of line above them rather than by counting back from
    the first labelled field, which would reach the addressee's own name.
    """
    covered = _covered(_ADDRESS_COLUMN)
    assert "Flat 9, Nehru Apartments\nStation Road" in covered
    assert not any("Ramesh" in value or "Basant" in value for value in covered)


def test_an_address_nothing_can_read_is_covered_by_the_shape_of_its_block() -> None:
    """The second copy of the address, in the language the card was issued in.

    An e-Aadhaar embeds fonts that hand back nothing usable for most Indic scripts, so
    neither the word above the block nor anything inside it can be matched, though all
    of it is perfectly legible to whoever opens the file. What is left to go on is the
    shape: a run of lines ending on the six-digit PIN, under the last thing the card
    keeps readable.
    """
    text = "Basant Raj\n/ MALE\n2345 6789 0124\n(cid:30)(cid:31)\n(cid:34)(cid:35)\n, 844101\n"
    covered = _covered(text)
    assert any("(cid:30)(cid:31)" in value and value.endswith("844101") for value in covered)
    # The walk stops at the line above, so what the card is shown to prove survives.
    assert not any("MALE" in value or "Basant" in value for value in covered)


def test_an_ordinary_document_is_not_put_through_the_aadhaar_address_rule() -> None:
    """The block walk is the Aadhaar plan's, and an invoice is not an Aadhaar."""
    text = "Order 4471\nThank you for your custom\nTotal 129.40\nReference 844101\n"
    assert _covered(text, scheme="") == set()


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


def test_two_codes_on_one_page_do_not_come_back_as_one_enormous_code() -> None:
    """An e-Aadhaar prints the card twice on a sheet, so it carries two codes.

    Gathering whatever hits lay within reach of each other read the pair as a single
    symbol spanning both, and the bar that followed covered everything printed
    between them, which on an Aadhaar is most of the card.
    """
    from PIL import Image

    symbol = _qr_image(modules=29, scale=5, margin=20)
    page = Image.new("RGB", (900, 700), "white")
    page.paste(symbol, (40, 40))
    page.paste(symbol, (620, 460))
    boxes = find_qr_codes(page)
    assert len(boxes) == 2, boxes
    for (x0, y0, x1, y1), (left, top) in zip(sorted(boxes), ((40, 40), (620, 460)), strict=True):
        assert abs(x0 - (left + 20)) <= 5 and abs(y0 - (top + 20)) <= 5
        assert abs((x1 - x0) - 145) <= 10 and abs((y1 - y0) - 145) <= 10


def test_a_photograph_is_told_from_the_artwork_printed_beside_it() -> None:
    """A card's pictures are mostly its logos, its banners and the rules between them.

    Painting those out defaces the copy for whoever receives it while withholding
    nothing, and a copy that looks destroyed is one the person sends the original
    instead of. What a box is for is the face.
    """
    import random

    from PIL import Image, ImageDraw

    from aletheia.analysis.documents.redact import _is_photograph

    page_area = 612.0 * 540.0
    rng = random.Random(11)
    face = Image.new("RGB", (160, 200))
    pixels = face.load()
    for y in range(face.height):
        for x in range(face.width):
            pixels[x, y] = tuple(rng.randint(60, 220) for _ in range(3))
    # A wide banner in two flat colours, the shape of the one across an Aadhaar's head.
    banner = Image.new("RGB", (920, 266), "white")
    ImageDraw.Draw(banner).rectangle((0, 90, 920, 180), fill="#ff7722")
    # A block of standing advice the issuer ships as a picture rather than as text.
    advice = Image.new("RGB", (1063, 1636), "white")
    ImageDraw.Draw(advice).text((40, 40), "Aadhaar is a proof of identity", fill="black")

    assert _is_photograph((40.0, 50.0, 136.0, 170.0), face, page_area)
    assert not _is_photograph((32.0, 103.0, 292.0, 265.0), banner, page_area)
    assert not _is_photograph((302.0, 169.0, 561.0, 578.0), advice, page_area)
    # A picture that will not decode is covered rather than trusted.
    assert _is_photograph((32.0, 103.0, 292.0, 265.0), None, page_area)


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
