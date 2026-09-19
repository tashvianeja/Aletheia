from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from privacy_guardian.analysis.pii.validators import (
    IBAN_LENGTHS,
    aba_checksum,
    iban_mod97,
    luhn,
    nhs_mod11,
    passport_mrz,
    ssn_structure,
)
from privacy_guardian.core.events import DataCategory, Finding

_HASH_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class Match:
    category: DataCategory
    start: int
    end: int
    confidence: float
    validator_passed: bool = False


# Only offsets exist outside this module; matched strings are never attached to results.
_PATTERNS: tuple[tuple[str, str, float], ...] = (
    (
        "email",
        r"(?<![\w.+-])[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+",
        0.99,
    ),
    ("government_id.ssn", r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)", 0.99),
    ("financial.card_number", r"(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)", 0.99),
    ("financial.iban", r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", 0.99),
    (
        "credentials.private_key",
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
        1,
    ),
    (
        "credentials.api_key",
        r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,})\b",
        0.99,
    ),
    (
        "postal_address",
        r"\b\d{1,6}\s+(?:[A-Z0-9][\w.\x27-]*\s+){1,5}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way|Court|Ct|Place|Pl)\b(?:[., ]+(?:Apt|Suite|Unit)\s*[\w-]+)?",
        0.85,
    ),
    ("government_id.passport", r"(?m)^P<[A-Z<]{3}[A-Z<]{39}\r?\n[A-Z0-9<]{44}$", 0.99),
)
_CONTEXT_PATTERNS: tuple[tuple[str, str, float], ...] = (
    (
        "full_name",
        r"(?:full\s*name|patient\s*name|surname|given\s*names?|name)\s*[:=]\s*([A-Z][A-Z\x27-]+(?:[ \t]+[A-Z][A-Z\x27-]+){0,4})",
        0.9,
    ),
    (
        "dob",
        r"(?:date\s+of\s+birth|birth\s*date|dob|born)\s*[:=]?\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}\s+[A-Z]{3,9}\s+\d{4}|[A-Z]{3,9}\s+\d{1,2},?\s+\d{4})",
        0.96,
    ),
    (
        "government_id.passport",
        r"passport(?:\s*(?:no\.?|number|#))?\s*[:=]?\s*([A-Z]{0,3}\d{6,9}|[A-Z0-9]{9})\b",
        0.92,
    ),
    (
        "government_id.national_id",
        r"(?:national\s*(?:id|identity)|aadhaar|aadhar)\s*(?:number|no\.?)?\s*[:=]?\s*([A-Z0-9][A-Z0-9 -]{5,19})",
        0.85,
    ),
    ("government_id.ssn", r"(?:ssn|social\s+security(?:\s+number)?)\s*[:=]?\s*(\d{9})\b", 0.99),
    (
        "government_id.drivers_license",
        r"(?:driver[\x27s]*\s*licen[cs]e|driving\s*licen[cs]e)\s*(?:number|no\.?)?\s*[:=]?\s*([A-Z0-9][A-Z0-9-]{5,19})",
        0.88,
    ),
    (
        "government_id.tax_id",
        r"(?:tax\s*(?:id|identification)|pan|tin|ein)\s*(?:number)?\s*[:=]\s*([A-Z0-9-]{7,15})",
        0.88,
    ),
    (
        "financial.account_number",
        r"(?:bank\s*)?account\s*(?:number|no\.?|#)\s*[:=]?\s*(\d[\d -]{5,20}\d)",
        0.9,
    ),
    ("financial.routing", r"(?:routing|aba)\s*(?:number|no\.?)?\s*[:=]?\s*(\d{9})", 0.99),
    (
        "medical.insurance_id",
        r"(?:nhs|insurance|patient|member)\s*(?:id|number|no\.?)\s*[:=]?\s*([A-Z0-9][A-Z0-9 -]{5,19})",
        0.9,
    ),
    (
        "medical.diagnosis",
        r"(?:diagnosis|diagnosed\s+with|medical\s+condition)\s*[:=]?\s*([^\n.;]{3,80})",
        0.9,
    ),
    (
        "medical.medication",
        r"(?:medication|prescribed|prescription)\s*[:=]?\s*([^\n.;]{3,80})",
        0.9,
    ),
    (
        "credentials.password",
        r"(?:password|passwd|pwd)\s*[:=]\s*[\x22\x27]?([^\s\x22\x27,;]{4,100})",
        0.95,
    ),
    (
        "credentials.api_key",
        r"(?:api[_ -]?key|secret[_ -]?key|access[_ -]?token|bearer)\s*[:= ]\s*[\x22\x27]?([A-Za-z0-9_./+=-]{12,200})",
        0.96,
    ),
    (
        "location_precise",
        r"(?:GPS|coordinates|latitude|longitude)\s*[:=]?\s*(-?\d{1,3}\.\d{3,}(?:[, ]+-?\d{1,3}\.\d{3,})?)",
        0.95,
    ),
)
_COMPILED = [
    (DataCategory(category), re.compile(pattern, re.I), confidence)
    for category, pattern, confidence in _PATTERNS
]
_CONTEXT = [
    (DataCategory(category), re.compile(pattern, re.I), confidence)
    for category, pattern, confidence in _CONTEXT_PATTERNS
]


@lru_cache(maxsize=1)
def _ner() -> Any:
    try:
        import spacy

        return spacy.load("en_core_web_sm", disable=["parser", "tagger", "lemmatizer"])
    except (ImportError, OSError):
        return None


def _validate(category: DataCategory, value: str) -> bool | None:
    validators = {
        DataCategory.FINANCIAL_CARD_NUMBER: luhn,
        DataCategory.FINANCIAL_IBAN: iban_mod97,
        DataCategory.GOVERNMENT_ID_SSN: ssn_structure,
        DataCategory.FINANCIAL_ROUTING: aba_checksum,
    }
    if category in validators:
        return validators[category](value)
    if category == DataCategory.GOVERNMENT_ID_PASSPORT and value.startswith("P<"):
        return passport_mrz(value)
    return None


def find_matches(text: str, *, use_ner: bool = False, region: str = "US") -> list[Match]:
    token_pattern = (
        r"<(?:" + "|".join(re.escape(category.value.upper()) for category in DataCategory) + r")>"
    )
    text = re.sub(token_pattern, lambda match: "\x00" * len(match.group()), text)
    matches: list[Match] = []
    for category, pattern, confidence in _COMPILED:
        for match in pattern.finditer(text):
            end = match.end()
            value = match.group()
            if category == DataCategory.FINANCIAL_IBAN:
                length = IBAN_LENGTHS.get(value[:2].upper(), 0)
                positions = [index for index, char in enumerate(value) if not char.isspace()]
                if not length or len(positions) < length:
                    continue
                end = match.start() + positions[length - 1] + 1
                value = text[match.start() : end]
            valid = _validate(category, value)
            if valid is False:
                continue
            # IBAN candidates greedily include adjacent prose; retry legal country length.
            matches.append(Match(category, match.start(), end, confidence, valid is True))
    for category, pattern, confidence in _CONTEXT:
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            if value.startswith("\x00"):
                continue
            valid = _validate(category, value)
            if valid is False:
                continue
            if category == DataCategory.MEDICAL_INSURANCE_ID and "nhs" in match.group().lower():
                valid = nhs_mod11(value)
                if not valid:
                    continue
            matches.append(Match(category, match.start(1), match.end(1), confidence, valid is True))
    try:
        import phonenumbers

        for phone in phonenumbers.PhoneNumberMatcher(text, region):
            if phonenumbers.is_valid_number(phone.number) and not any(
                item.start <= phone.start < item.end
                and item.category
                in {
                    DataCategory.FINANCIAL_CARD_NUMBER,
                    DataCategory.FINANCIAL_IBAN,
                    DataCategory.GOVERNMENT_ID_SSN,
                }
                for item in matches
            ):
                matches.append(Match(DataCategory.PHONE, phone.start, phone.end, 0.95, True))
    except ImportError:
        for match in re.finditer(
            r"(?<!\w)(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", text
        ):
            matches.append(Match(DataCategory.PHONE, match.start(), match.end(), 0.7))
    if re.search(r"\b(?:street|avenue|road|boulevard|address)\b", text, re.I):
        try:
            import pyap

            for address in pyap.parse(text, country="US"):
                value = str(address)
                start = text.find(value)
                if start >= 0:
                    matches.append(
                        Match(DataCategory.POSTAL_ADDRESS, start, start + len(value), 0.9)
                    )
        except (ImportError, ValueError):
            pass
    if use_ner:
        nlp = _ner()
        if nlp is not None:
            for entity in nlp(text[:200_000]).ents:
                entity_category = {
                    "PERSON": DataCategory.FULL_NAME,
                    "GPE": DataCategory.LOCATION_COARSE,
                }.get(entity.label_)
                if entity_category is not None:
                    matches.append(Match(entity_category, entity.start_char, entity.end_char, 0.7))
                elif entity.label_ == "ORG" and re.search(
                    r"employer|employed|work(?:ing)? at",
                    text[max(0, entity.start_char - 40) : entity.start_char],
                    re.I,
                ):
                    matches.append(
                        Match(DataCategory.EMPLOYMENT, entity.start_char, entity.end_char, 0.65)
                    )
    unique = {(match.category, match.start, match.end): match for match in matches}
    return sorted(
        unique.values(), key=lambda match: (match.start, -match.end, match.category.value)
    )


def detect_pii(text: str, *, page: int | None = None, use_ner: bool = False) -> list[Finding]:
    result = []
    for match in find_matches(text, use_ner=use_ner):
        digest = hashlib.blake2b(
            (match.category.value + "\0" + text[match.start : match.end]).encode(),
            key=_HASH_KEY,
            digest_size=20,
        ).hexdigest()
        result.append(
            Finding(
                category=match.category,
                confidence=match.confidence,
                span_ref=f"{match.start}:{match.end}",
                page=page,
                validator_passed=match.validator_passed,
                stable_hash=digest,
            )
        )
    return result


def redact_text(
    text: str, categories: set[DataCategory] | None = None, *, use_ner: bool = False
) -> str:
    matches = [
        match
        for match in find_matches(text, use_ner=use_ner)
        if categories is None or match.category in categories
    ]
    # Merge intersecting spans before replacing, so one match cannot reveal part of another.
    groups: list[tuple[int, int, DataCategory]] = []
    for match in matches:
        if groups and match.start <= groups[-1][1]:
            start, end, category = groups[-1]
            groups[-1] = (start, max(end, match.end), category)
        else:
            groups.append((match.start, match.end, match.category))
    for start, end, category in reversed(groups):
        text = text[:start] + f"<{category.value.upper()}>" + text[end:]
    return text
