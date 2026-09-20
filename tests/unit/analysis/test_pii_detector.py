from __future__ import annotations

import re

from aletheia.analysis.pii import detect_pii, redact_text
from aletheia.core.events import DataCategory

SYNTHETIC_TEXT = """
Full name: Morgan Testperson
DOB: 1988-02-29
Passport number: X12345678
Email: morgan.testperson@example.test
Test card: 4111 1111 1111 1111
IBAN: GB82 WEST 1234 5698 7654 32
SSN: 219-09-9999
Routing number: 021000021
Diagnosis: synthetic influenza
Medication: test tablets
Password: synthetic-only-secret
GPS coordinates: 0.0000, 0.0000
""".strip()


def test_detector_finds_validated_and_contextual_synthetic_pii_without_values() -> None:
    findings = detect_pii(SYNTHETIC_TEXT, page=2)
    categories = {finding.category for finding in findings}
    assert {
        DataCategory.FULL_NAME,
        DataCategory.DOB,
        DataCategory.GOVERNMENT_ID_PASSPORT,
        DataCategory.EMAIL,
        DataCategory.FINANCIAL_CARD_NUMBER,
        DataCategory.FINANCIAL_IBAN,
        DataCategory.GOVERNMENT_ID_SSN,
        DataCategory.FINANCIAL_ROUTING,
        DataCategory.MEDICAL_DIAGNOSIS,
        DataCategory.MEDICAL_MEDICATION,
        DataCategory.CREDENTIALS_PASSWORD,
        DataCategory.LOCATION_PRECISE,
    } <= categories
    # The keyed hash is opaque hex that no value can be read out of, and a short
    # digit run turns up inside one by chance often enough to fail this on its own.
    serialized = "".join(finding.model_dump_json(exclude={"stable_hash"}) for finding in findings)
    for raw_value in ("Morgan", "4111", "X12345678", "synthetic-only-secret"):
        assert raw_value not in serialized
    assert all(re.fullmatch(r"[0-9a-f]{40}", finding.stable_hash) for finding in findings)
    assert all(finding.page == 2 for finding in findings)


def test_validator_confirmed_categories_set_validator_flag() -> None:
    findings = detect_pii("Card 4111111111111111; SSN 219-09-9999; routing 021000021")
    validated = {finding.category for finding in findings if finding.validator_passed}
    assert DataCategory.FINANCIAL_CARD_NUMBER in validated
    assert DataCategory.GOVERNMENT_ID_SSN in validated


def test_invalid_checksum_candidates_are_not_reported_as_validated_identifiers() -> None:
    findings = detect_pii(
        "Invalid card 4111111111111112 and invalid IBAN GB82 WEST 1234 5698 7654 31"
    )
    categories = {finding.category for finding in findings}
    assert DataCategory.FINANCIAL_CARD_NUMBER not in categories
    assert DataCategory.FINANCIAL_IBAN not in categories


def test_stable_hash_deduplicates_same_value_without_cross_category_collision() -> None:
    first = detect_pii("Email: morgan.testperson@example.test")
    second = detect_pii("Contact morgan.testperson@example.test today")
    assert first[0].stable_hash == second[0].stable_hash
    assert len(first[0].stable_hash) >= 32


def test_redacted_text_rescans_clean_for_selected_categories() -> None:
    redacted = redact_text(SYNTHETIC_TEXT)
    rescanned = detect_pii(redacted)
    assert not rescanned
    assert "Morgan Testperson" not in redacted
    assert "4111 1111 1111 1111" not in redacted
    assert "synthetic-only-secret" not in redacted


def test_selective_redaction_does_not_remove_unselected_category() -> None:
    source = "Email morgan.testperson@example.test, card 4111111111111111"
    redacted = redact_text(source, {DataCategory.FINANCIAL_CARD_NUMBER})
    assert "morgan.testperson@example.test" in redacted
    assert "4111111111111111" not in redacted


def test_iban_is_detected_when_followed_by_ordinary_prose() -> None:
    findings = detect_pii("Transfer to GB82 WEST 1234 5698 7654 32 today please.")
    assert any(
        finding.category == DataCategory.FINANCIAL_IBAN and finding.validator_passed
        for finding in findings
    )


def test_multiline_private_key_and_spaced_card_are_detected_without_serializing_values() -> None:
    private_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "SYNTHETICONLYABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n"
        "-----END PRIVATE KEY-----"
    )
    card = "4111-1111-1111-1111"
    findings = detect_pii(f"{private_key}\nTest card: {card}")
    categories = {finding.category for finding in findings}
    assert DataCategory.CREDENTIALS_PRIVATE_KEY in categories
    assert DataCategory.FINANCIAL_CARD_NUMBER in categories
    serialized = "".join(finding.model_dump_json() for finding in findings)
    assert "SYNTHETICONLY" not in serialized
    assert card not in serialized


def test_ner_finds_unlabelled_person_late_in_large_text_and_across_chunk_boundary() -> None:
    prefix = "ordinary synthetic narrative " * 9000
    boundary_prefix = "x" * (8192 - 8)
    source = prefix + "\n" + boundary_prefix + " Alice Testperson attended the synthetic meeting."
    findings = detect_pii(source, use_ner=True)
    assert any(finding.category == DataCategory.FULL_NAME for finding in findings)
    assert "Alice Testperson" not in "".join(finding.model_dump_json() for finding in findings)


AADHAAR_TEXT = """
GOVERNMENT OF INDIA
Unique Identification Authority of India
Name: Morgan Testperson
DOB: 29/02/1988
Gender: Female
2345 6789 0124
VID : 9012 3456 7890 1235
Address: S/O Jordan Testperson, 12 Nehru Marg,
Ward 4, Kanpur Nagar, Uttar Pradesh 208001
Mobile: 9876543210
""".strip()


def _values(text: str, category: DataCategory) -> set[str]:
    return {
        text[int(finding.span_ref.split(":")[0]) : int(finding.span_ref.split(":")[1])]
        for finding in detect_pii(text, use_ner=True)
        if finding.category == category
    }


def test_an_aadhaar_card_gives_up_its_number_vid_address_and_mobile() -> None:
    """The number is printed bare, so the card around it is what says what it is."""
    assert {"2345 6789 0124", "9012 3456 7890 1235"} <= _values(
        AADHAAR_TEXT, DataCategory.GOVERNMENT_ID_NATIONAL_ID
    )
    assert "9876543210" in _values(AADHAAR_TEXT, DataCategory.PHONE)
    # An Indian address ends in a PIN rather than a street suffix, and runs over lines.
    [address] = [
        value for value in _values(AADHAAR_TEXT, DataCategory.POSTAL_ADDRESS) if "Nehru" in value
    ]
    assert address.endswith("208001")


def test_twelve_digits_on_a_page_that_is_not_an_aadhaar_card_are_left_alone() -> None:
    """A checksum alone would call one invoice line in ten somebody's national ID."""
    invoice = "Invoice 2345 6789 0124 for order 9012 3456 7890 1235, paid 02/02/2024."
    assert not _values(invoice, DataCategory.GOVERNMENT_ID_NATIONAL_ID)
    # The same digits, on a card that names the scheme, are exactly what to look for.
    assert _values("Aadhaar card\n" + invoice, DataCategory.GOVERNMENT_ID_NATIONAL_ID)


def test_a_number_that_fails_its_checksum_is_not_reported_as_an_aadhaar() -> None:
    card = AADHAAR_TEXT.replace("2345 6789 0124", "2345 6789 0125")
    assert "2345 6789 0125" not in _values(card, DataCategory.GOVERNMENT_ID_NATIONAL_ID)
