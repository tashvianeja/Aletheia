from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from privacy_guardian.analysis.pii.validators import (
    IBAN_LENGTHS,
    aadhaar_number,
    aadhaar_vid,
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
    # The Virtual ID a card prints under its Aadhaar number. It is always labelled,
    # so the label is enough to find it and the checksum settles whether it is one.
    (
        "government_id.national_id",
        r"\bV\.?I\.?D\.?\s*(?:number|no\.?)?\s*[:=]?\s*((?:\d{4}[ -]?){3}\d{4})\b",
        0.95,
    ),
    # An Indian mobile number is ten digits opening 6-9 and is written without a
    # country code as often as with one, which `phonenumbers` cannot place on its own.
    (
        "phone",
        r"(?:mobile|mob\.?|phone|contact)\s*(?:number|no\.?|#)?\s*[:=]?\s*((?:\+?91[ -]?)?[6-9]\d{9})(?!\d)",
        0.9,
    ),
    # An address that ends in a six-digit PIN: the street-suffix patterns above are
    # written for US and UK addresses and do not see an Indian one at all.
    (
        "postal_address",
        r"(?:address|पता)\s*[:=]?\s*((?:[^\n]{1,80}\n){0,4}?[^\n]{0,80}?\b\d{6}\b)",
        0.9,
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
# What says a block of text came off an Aadhaar card. The number itself is printed
# bare, in a 4-4-4 group with nothing to label it, so nothing but the card around it
# tells an Aadhaar number apart from any other twelve digits. Matching it only where
# one of these appears is what keeps a reference number on an invoice from being
# announced to the person as their national ID; the checksum then does the rest.
_AADHAAR_MARKERS = re.compile(
    r"aadhaar|aadhar|आधार|uidai|unique\s+identification\s+authority"
    r"|government\s+of\s+india|भारत\s*सरकार|\bvid\b",
    re.I,
)
# A bare Aadhaar number as the card prints it: 4-4-4, or run together.
_AADHAAR_BARE = re.compile(r"(?<!\d)([2-9]\d{3}[ -]?\d{4}[ -]?\d{4})(?!\d)")
# A bare Virtual ID, which is sixteen digits in the same 4-4-4-4 shape.
_VID_BARE = re.compile(r"(?<!\d)(\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4})(?!\d)")
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

        return spacy.load(
            "en_core_web_sm",
            exclude=["tok2vec", "parser", "tagger", "lemmatizer", "attribute_ruler"],
        )
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


def _find_matches_block(text: str, *, use_ner: bool = False, region: str = "US") -> list[Match]:
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
            if category == DataCategory.GOVERNMENT_ID_NATIONAL_ID:
                digits = re.sub(r"[ -]", "", value)
                # Other countries' national IDs carry no checksum we can test, so only a
                # value shaped like an Aadhaar number or a VID has to survive Verhoeff.
                if len(digits) == 12 and digits.isdigit():
                    valid = aadhaar_number(value)
                elif len(digits) == 16 and digits.isdigit():
                    valid = aadhaar_vid(value)
                if valid is False:
                    continue
            matches.append(Match(category, match.start(1), match.end(1), confidence, valid is True))
    if _AADHAAR_MARKERS.search(text):
        for pattern, validator in ((_AADHAAR_BARE, aadhaar_number), (_VID_BARE, aadhaar_vid)):
            for match in pattern.finditer(text):
                if validator(match.group(1)):
                    matches.append(
                        Match(
                            DataCategory.GOVERNMENT_ID_NATIONAL_ID,
                            match.start(1),
                            match.end(1),
                            0.95,
                            True,
                        )
                    )
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
            # Inspect every character, with overlap for entities spanning chunk boundaries.
            # Repeated clauses/rows share an inference result, preserving original offsets.
            chunks: list[tuple[int, str]] = []
            offset = 0
            while offset < len(text):
                end = min(len(text), offset + 8192)
                if end < len(text):
                    boundary = text.rfind("\n", offset + 4096, end)
                    if boundary >= 0:
                        end = boundary + 1
                start = max(0, offset - 256)
                chunks.append((start, text[start : min(len(text), end + 256)]))
                offset = end
            unique_chunks = dict.fromkeys(chunk for _, chunk in chunks)
            entities_by_chunk = {
                chunk: [
                    (entity.start_char, entity.end_char, entity.label_) for entity in document.ents
                ]
                for chunk, document in zip(
                    unique_chunks, nlp.pipe(unique_chunks, batch_size=8), strict=True
                )
            }
            for start, chunk in chunks:
                for begin, end, label in entities_by_chunk[chunk]:
                    begin += start
                    end += start
                    entity_category = {
                        "PERSON": DataCategory.FULL_NAME,
                        "GPE": DataCategory.LOCATION_COARSE,
                    }.get(label)
                    if entity_category is not None:
                        matches.append(Match(entity_category, begin, end, 0.7))
                    elif label == "ORG" and re.search(
                        r"employer|employed|work(?:ing)? at", text[max(0, begin - 40) : begin], re.I
                    ):
                        matches.append(Match(DataCategory.EMPLOYMENT, begin, end, 0.65))
    unique = {(match.category, match.start, match.end): match for match in matches}
    return sorted(
        unique.values(), key=lambda match: (match.start, -match.end, match.category.value)
    )


def find_matches(text: str, *, use_ner: bool = False, region: str = "US") -> list[Match]:
    if len(text) <= 65_536:
        return _find_matches_block(text, use_ner=use_ner, region=region)
    # Repeated exported rows and boilerplate need one analysis per distinct window.
    # Overlap preserves ordinary identifiers, addresses and multi-line name context.
    cache: dict[str, list[Match]] = {}
    found: dict[tuple[DataCategory, int, int], Match] = {}
    offset = 0
    while offset < len(text):
        end = min(len(text), offset + 16_384)
        if end < len(text):
            boundary = text.rfind("\n", offset + 8192, end)
            if boundary >= 0:
                end = boundary + 1
        start = max(0, offset - 512)
        chunk = text[start : min(len(text), end + 512)]
        matches = cache.get(chunk)
        if matches is None:
            matches = _find_matches_block(chunk, use_ner=use_ner, region=region)
            cache[chunk] = matches
        for match in matches:
            shifted = Match(
                match.category,
                match.start + start,
                match.end + start,
                match.confidence,
                match.validator_passed,
            )
            found[(shifted.category, shifted.start, shifted.end)] = shifted
        offset = end
    # Credentials can legitimately exceed the overlap (for example PEM keys).
    # Scan these unbounded patterns over the complete text as well.
    for category, pattern, confidence in _COMPILED:
        if category.value.startswith("credentials."):
            for candidate in pattern.finditer(text):
                found[(category, candidate.start(), candidate.end())] = Match(
                    category, candidate.start(), candidate.end(), confidence
                )
    for category, pattern, confidence in _CONTEXT:
        if category.value.startswith("credentials."):
            for candidate in pattern.finditer(text):
                found[(category, candidate.start(1), candidate.end(1))] = Match(
                    category, candidate.start(1), candidate.end(1), confidence
                )
    return sorted(found.values(), key=lambda match: (match.start, -match.end, match.category.value))


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
