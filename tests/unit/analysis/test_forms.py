from __future__ import annotations

import pytest
from pydantic import ValidationError

from aletheia.analysis.forms import analyze_fields, label_field
from aletheia.core.events import DataCategory, FormField


@pytest.mark.parametrize(
    ("field", "category"),
    [
        (FormField(field_id="a", autocomplete="tel"), DataCategory.PHONE),
        (FormField(field_id="b", input_type="email"), DataCategory.EMAIL),
        (FormField(field_id="c", label="Date de naissance"), DataCategory.DOB),
        (FormField(field_id="d", label="Dirección postal"), DataCategory.POSTAL_ADDRESS),
        (FormField(field_id="e", label="Reisepassnummer"), DataCategory.GOVERNMENT_ID_PASSPORT),
    ],
)
def test_field_labelling_uses_semantic_metadata_in_supported_languages(
    field: FormField, category: DataCategory
) -> None:
    labelled = label_field(field)
    assert labelled.category == category
    assert labelled.confidence >= 0.9


def test_autocomplete_has_precedence_over_misleading_name() -> None:
    field = FormField(field_id="telephone-looking-name", name="phone", autocomplete="email")
    assert label_field(field).category == DataCategory.EMAIL


def test_form_field_contract_cannot_carry_value_or_default_value() -> None:
    with pytest.raises(ValidationError):
        FormField(field_id="password", input_type="password", value="synthetic-secret")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        FormField(field_id="card", default_value="4111111111111111")  # type: ignore[call-arg]


def test_free_download_flags_only_unnecessary_sensitive_fields() -> None:
    fields = [
        FormField(field_id="name", autocomplete="name", filled=True),
        FormField(field_id="email", input_type="email", filled=True),
        FormField(field_id="phone", autocomplete="tel", filled=True),
        FormField(field_id="dob", autocomplete="bday", filled=True),
        FormField(field_id="address", autocomplete="street-address", filled=True),
    ]
    assessments = analyze_fields(fields, purpose="free_download", purpose_confidence=0.95)
    badges = {item.field.category for item in assessments if item.badge}
    assert badges == {DataCategory.PHONE, DataCategory.DOB, DataCategory.POSTAL_ADDRESS}


def test_bank_kyc_does_not_badge_dob_or_address() -> None:
    fields = [
        FormField(field_id="dob", autocomplete="bday", required=True),
        FormField(field_id="address", autocomplete="street-address", required=True),
    ]
    assessments = analyze_fields(fields, purpose="banking", purpose_confidence=0.95)
    assert all(not item.badge for item in assessments)
    assert all(not item.optional for item in assessments)


def test_asserted_required_remains_distinct_from_html_required() -> None:
    field = FormField(
        field_id="phone", autocomplete="tel", required=False, asserted_required=True, filled=False
    )
    assessment = analyze_fields([field], purpose="free_download")[0]
    assert assessment.optional is True
    assert assessment.field.asserted_required is True
