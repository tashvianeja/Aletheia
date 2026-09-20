from __future__ import annotations

import pytest

from privacy_guardian.analysis.pii.validators import (
    aadhaar_number,
    aadhaar_vid,
    aba_checksum,
    iban_mod97,
    luhn,
    nhs_mod11,
    passport_mrz,
    ssn_structure,
    verhoeff,
    verhoeff_digit,
)


@pytest.mark.parametrize(
    "value", ["4111111111111111", "5555 5555 5555 4444", "4000-0000-0000-0002"]
)
def test_luhn_accepts_published_test_ranges(value: str) -> None:
    assert luhn(value)


@pytest.mark.parametrize("value", ["4111111111111112", "0000000000000000", "not a card", "4111"])
def test_luhn_rejects_invalid_and_degenerate_values(value: str) -> None:
    assert not luhn(value)


@pytest.mark.parametrize("value", ["GB82 WEST 1234 5698 7654 32", "DE89370400440532013000"])
def test_iban_mod97_accepts_public_examples(value: str) -> None:
    assert iban_mod97(value)


@pytest.mark.parametrize(
    "value", ["GB82 WEST 1234 5698 7654 31", "US12INVALID", "DE00370400440532013000"]
)
def test_iban_mod97_rejects_bad_check_digits_or_country(value: str) -> None:
    assert not iban_mod97(value)


@pytest.mark.parametrize("value", ["021000021", "011000015"])
def test_aba_checksum_accepts_public_bank_routing_examples(value: str) -> None:
    assert aba_checksum(value)


@pytest.mark.parametrize("value", ["021000022", "000000000", "991000019"])
def test_aba_checksum_rejects_bad_checksum_or_prefix(value: str) -> None:
    assert not aba_checksum(value)


def test_nhs_mod11_accepts_documented_synthetic_example() -> None:
    assert nhs_mod11("943 476 5919")
    assert not nhs_mod11("943 476 5918")


@pytest.mark.parametrize("value", ["219-09-9999", "001010001"])
def test_ssn_structure_accepts_structurally_valid_synthetic_values(value: str) -> None:
    assert ssn_structure(value)


@pytest.mark.parametrize(
    "value", ["000-12-3456", "666-12-3456", "900-12-3456", "123-00-1234", "123-45-0000"]
)
def test_ssn_structure_rejects_disallowed_ranges(value: str) -> None:
    assert not ssn_structure(value)


def test_passport_mrz_validates_all_td3_check_digits() -> None:
    valid = (
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10"
    )
    assert passport_mrz(valid)
    assert not passport_mrz(valid[:-1] + "1")


@pytest.mark.parametrize("value", ["2345 6789 0124", "234567890124", "9999-8888-7779"])
def test_aadhaar_number_accepts_twelve_digits_that_pass_verhoeff(value: str) -> None:
    assert aadhaar_number(value)


@pytest.mark.parametrize(
    "value",
    [
        # One digit off the checksum, and two neighbours swapped: Verhoeff catches both.
        "2345 6789 0125",
        "2345 6798 0124",
        # UIDAI issues nothing opening 0 or 1, so a padded reference is not an Aadhaar.
        "0345 6789 0128",
        "1234 5678 9015",
        "222222222222",
        "2345 6789 01",
    ],
)
def test_aadhaar_number_rejects_bad_checksums_leading_digits_and_lengths(value: str) -> None:
    assert not aadhaar_number(value)


def test_aadhaar_vid_takes_sixteen_digits_where_the_number_takes_twelve() -> None:
    assert aadhaar_vid("9012 3456 7890 1235")
    assert not aadhaar_vid("9012 3456 7890 1234")
    # The twelve-digit number is not a VID, whatever its own checksum says.
    assert not aadhaar_vid("2345 6789 0124")


def test_verhoeff_digit_completes_a_number_its_check_accepts() -> None:
    for body in ("23456789012", "901234567890123", "7"):
        assert verhoeff(body + verhoeff_digit(body))
