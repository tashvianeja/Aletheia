from __future__ import annotations

import re

from pydantic import BaseModel

from privacy_guardian.core.events import DataCategory, FormField
from privacy_guardian.engine.necessity import Necessity, NecessityAssessment, necessity_for

_AUTOCOMPLETE = {
    "name": "full_name",
    "given-name": "full_name",
    "family-name": "full_name",
    "email": "email",
    "tel": "phone",
    "street-address": "postal_address",
    "address-line1": "postal_address",
    "address-line2": "postal_address",
    "postal-code": "postal_address",
    "bday": "dob",
    "bday-day": "dob",
    "bday-month": "dob",
    "bday-year": "dob",
    "sex": "gender",
    "current-password": "credentials.password",
    "new-password": "credentials.password",
    "cc-number": "financial.card_number",
    "cc-name": "full_name",
    "organization-title": "employment",
}
_LEXICON: dict[str, str] = {
    "government_id.passport": r"passport|passeport|reisepass|pasaporte",
    "government_id.ssn": r"\bssn\b|social.?security|sozialversicher",
    "government_id.national_id": r"national.?id|identity.?number|personalausweis|identit[eé]|identidad|aadhaar",
    "financial.card_number": r"card.?number|credit.?card|carte.?bancaire|kreditkarte|tarjeta",
    "financial.iban": r"\biban\b",
    "financial.account_number": r"bank.?account|account.?number|kontonummer|compte.?bancaire|cuenta.?bancaria",
    "medical": r"diagnosis|medication|medical|health.?condition|diagnostic|m[eé]dical|gesundheit|salud",
    "dob": r"birth|\bdob\b|geburt|naissance|nacimiento",
    "age": r"\bage\b|\balter\b|\bedad\b|\bâge\b",
    "phone": r"phone|mobile|\btel\b|t[eé]l[eé]phone|telefon|tel[eé]fono",
    "postal_address": r"address|street|postal|postcode|zip.?code|adresse|anschrift|stra[sß]e|direcci[oó]n|domicilio",
    "email": r"e.?mail|courriel|correo",
    "full_name": r"\bname\b|first.?name|last.?name|surname|vorname|nachname|\bnom\b|pr[eé]nom|nombre|apellido",
    "credentials.password": r"password|passwd|passwort|mot.?de.?passe|contrase[nñ]a",
    "gender": r"gender|\bsex\b|sexe|geschlecht|g[eé]nero",
    "ethnicity_religion_orientation": r"ethnic|religion|orientation|race|religión",
    "employment": r"employer|occupation|job.?title|employment|arbeitgeber|profession|empleo",
    "education": r"education|degree|university|schule|universit[eé]|educaci[oó]n",
}


class FieldAssessment(BaseModel):
    field: FormField
    necessity: NecessityAssessment | None = None
    badge: bool = False
    optional: bool = True


def label_field(field: FormField) -> FormField:
    if field.category is not None:
        return field.model_copy()
    for token in field.autocomplete.lower().split():
        if token in _AUTOCOMPLETE:
            return field.model_copy(
                update={"category": DataCategory(_AUTOCOMPLETE[token]), "confidence": 0.99}
            )
    input_category = {"email": "email", "tel": "phone", "password": "credentials.password"}.get(
        field.input_type
    )
    if input_category:
        return field.model_copy(
            update={"category": DataCategory(input_category), "confidence": 0.98}
        )
    text = " ".join((field.label, field.name, field.field_id))
    for category, pattern in _LEXICON.items():
        if re.search(pattern, text, re.I):
            return field.model_copy(update={"category": DataCategory(category), "confidence": 0.9})
    return field.model_copy()


def analyze_fields(
    fields: list[FormField], purpose: str = "unknown", purpose_confidence: float = 1.0
) -> list[FieldAssessment]:
    result = []
    sensitive = {
        "phone",
        "dob",
        "postal_address",
        "government_id",
        "financial",
        "medical",
        "ethnicity_religion_orientation",
    }
    for field in fields:
        labelled = label_field(field)
        necessity = (
            necessity_for(purpose, labelled.category, purpose_confidence)
            if labelled.category
            else None
        )
        badge = (
            necessity is not None
            and necessity.verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}
            and labelled.category is not None
            and labelled.category.value.split(".")[0] in sensitive
        )
        result.append(
            FieldAssessment(
                field=labelled, necessity=necessity, badge=badge, optional=not labelled.required
            )
        )
    return result
