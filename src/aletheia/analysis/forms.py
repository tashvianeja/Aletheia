from __future__ import annotations

import re

from pydantic import BaseModel

from aletheia.core.events import DataCategory, FormContext, FormField
from aletheia.engine.necessity import NecessityAssessment

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
    "financial.card_number": r"card.?number|credit.?card|carte.?bancaire|kreditkarte|tarjeta|\bcvv\b|\bcvc\b|card.?(?:security|verification).?(?:code|value)",
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
    role: str = ""
    intent: str = "unknown"
    intent_confidence: float = 0.0


# The same words, meaning something else: an email address is not where you live, and
# the name of your first pet is not your name. Now that a field arrives carrying the
# question the page asked rather than a bare attribute, these decide far more fields.
_NOT_THIS_FIELD: dict[str, str] = {
    "postal_address": r"(?:e.?mail|ip|mac|web|url|wallet|server|billing e)\s?.?address",
    "full_name": r"names? (?:of|for)\b|(?:user|file|domain|product|company|pet|brand|screen|display|business|band|street)\s?names?",
    "age": r"average|age of consent",
    "email": r"e.?mail (?:preferences|frequency)",
}


def _lexicon_category(text: str) -> str | None:
    """The most specific category the wording supports, not the first one listed.

    "Email address" matched `address` before it matched `email`, purely because postal
    addresses sit higher in the table, and the form was then reported as asking a survey
    respondent for their home address. The longest piece of the label that a category
    can account for is the one that decides it.
    """
    best: tuple[int, str] | None = None
    for category, pattern in _LEXICON.items():
        match = re.search(pattern, text, re.I)
        if match is None:
            continue
        disqualifier = _NOT_THIS_FIELD.get(category)
        if disqualifier and re.search(disqualifier, text, re.I):
            continue
        length = match.end() - match.start()
        if best is None or length > best[0]:
            best = (length, category)
    return best[1] if best else None


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
    category = _lexicon_category(text)
    if category is not None:
        return field.model_copy(update={"category": DataCategory(category), "confidence": 0.9})
    return field.model_copy()


def analyze_fields(
    fields: list[FormField],
    purpose: str = "unknown",
    purpose_confidence: float = 1.0,
    context: FormContext | None = None,
) -> list[FieldAssessment]:
    """Judge a form's fields against what the form is for.

    Necessity used to be looked up from the site's industry category alone, which cannot
    tell a registration form from a mailing-list box and so reported Instagram's account
    identifier as unnecessary. The judgement now runs on the inferred intent of this
    form, with the site's purpose kept as a supporting signal.
    """
    from aletheia.intelligence.necessity import assess_form

    labelled = [label_field(field) for field in fields]
    judgement = assess_form(labelled, context, purpose)
    confidence = max(0.0, min(1.0, purpose_confidence))
    return [
        FieldAssessment(
            field=item.field,
            necessity=(
                NecessityAssessment(
                    category=item.field.category,
                    verdict=item.verdict,
                    confidence=min(item.confidence, confidence) if confidence else item.confidence,
                    rationale=item.rationale,
                )
                if item.field.category is not None
                else None
            ),
            badge=item.flag,
            # `optional` reports the HTML attribute; an asserted "*" stays distinct from it.
            optional=not item.field.required,
            role=item.role.value,
            intent=judgement.intent.intent.value,
            intent_confidence=judgement.intent.confidence,
        )
        for item in judgement.fields
    ]
