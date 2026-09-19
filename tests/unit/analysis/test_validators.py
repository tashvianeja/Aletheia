from __future__ import annotations

import pytest

from privacy_guardian.analysis.pii.validators import (
    aba_checksum,
    iban_mod97,
    luhn,
    nhs_mod11,
    passport_mrz,
    ssn_structure,
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
