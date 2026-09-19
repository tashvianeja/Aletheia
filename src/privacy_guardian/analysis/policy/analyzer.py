from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from pydantic import BaseModel, Field

from privacy_guardian.analysis.pii import redact_text
from privacy_guardian.core.events import DataCategory
from privacy_guardian.engine.labels import category_label
from privacy_guardian.engine.necessity import necessity_for


class Clause(BaseModel):
    category: str
    confidence: float = Field(default=0.9, ge=0, le=1)
    citation: str
    section: str = ""


class TermsProfile(BaseModel):
    document_hash: str
    clauses: list[Clause] = Field(default_factory=list)
    nothing_unusual: list[str] = Field(
        default_factory=lambda: ["payment", "account_creation", "basic_service_usage"]
    )
    missing: bool = False
    partial: bool = False


class PolicyProfile(BaseModel):
    document_hash: str
    collects: list[DataCategory] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    shares_with: list[str] = Field(default_factory=list)
    retention: Literal["stated_period", "until_deletion", "after_deletion", "unspecified"] = (
        "unspecified"
    )
    retention_period: str | None = None
    user_rights: list[str] = Field(default_factory=list)
    children: str = "unspecified"
    international_transfer: bool = False
    contact: str | None = None
    clauses: list[Clause] = Field(default_factory=list)
    necessity_statements: list[str] = Field(default_factory=list)
    missing: bool = False
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def patterns() -> dict[str, dict[str, list[str]]]:
    value: dict[str, dict[str, list[str]]] = json.loads(
        files("privacy_guardian.analysis.policy").joinpath("patterns/clauses.yaml").read_text()
    )
    return value


@lru_cache(maxsize=1)
def _compiled() -> dict[str, tuple[list[re.Pattern[str]], list[re.Pattern[str]], list[str]]]:
    return {
        key: (
            [re.compile(pattern, re.I) for pattern in item["positive"]],
            [re.compile(pattern, re.I) for pattern in item["negative"]],
            item["scope"],
        )
        for key, item in patterns().items()
    }


@lru_cache(maxsize=1)
def _segmenter() -> Any:
    import pysbd

    return pysbd.Segmenter(language="en", clean=False)


def sentences(text: str) -> list[tuple[str, str]]:
    # Line-aware segmentation preserves headings and avoids model loading in the hot path.
    result: list[tuple[str, str]] = []
    paragraph_segments: dict[str, tuple[str, ...]] = {}
    cached_characters = 0
    heading = ""
    for paragraph in re.split(r"\n+", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if (
            len(paragraph) < 90
            and not re.search(r"[.!?;]", paragraph)
            and (paragraph.endswith(":") or len(paragraph.split()) <= 5)
        ):
            heading = paragraph.rstrip(":")
        segmented = paragraph_segments.get(paragraph)
        if segmented is None:
            segmented = tuple(
                sentence.strip()
                for segment in _segmenter().segment(paragraph)
                for sentence in re.split(r";\s*|\s+(?:but|however|nevertheless)\s+", segment)
                if sentence.strip()
            )
            # Cache only segmentation, never headings or analysis decisions. Bound the
            # cache to this call and a small share of the document's memory budget.
            if len(paragraph_segments) < 256 and cached_characters + len(paragraph) <= 262_144:
                paragraph_segments[paragraph] = segmented
                cached_characters += len(paragraph)
        result.extend((sentence, heading) for sentence in segmented)
    return result


def _negated(text: str, start: int, end: int) -> bool:
    prefix = text[max(0, start - 55) : end]
    return bool(
        re.search(
            r"\b(?:do not|does not|will not|shall not|never|no longer|without|won\x27t|don\x27t)\b.{0,35}$",
            prefix[: max(0, start - max(0, start - 55))],
            re.I,
        )
    )


def analyze_terms(text: str) -> TermsProfile:
    return _terms_from_sentences(text, sentences(text[:2_000_000]))


def _terms_from_sentences(text: str, segmented: list[tuple[str, str]]) -> TermsProfile:
    digest = hashlib.sha256(text.encode()).hexdigest()
    if not text.strip():
        return TermsProfile(document_hash=digest, missing=True, nothing_unusual=[])
    found: dict[str, Clause] = {}
    for sentence, heading in segmented:
        for category, (positive, negative, scopes) in _compiled().items():
            if category in found:
                continue
            if any(pattern.search(sentence) for pattern in positive) and not any(
                pattern.search(sentence) for pattern in negative
            ):
                confidence = (
                    0.96 if any(scope.lower() in heading.lower() for scope in scopes) else 0.9
                )
                # Public clauses may still accidentally contain identifiers. Cache only sanitized citations.
                found[category] = Clause(
                    category=category,
                    confidence=confidence,
                    citation=redact_text(sentence)[:2000],
                    section=redact_text(heading)[:150],
                )
    normal = ["payment", "account_creation", "basic_service_usage"]
    if "automatic_renewal" in found or "liability_cap" in found:
        normal.remove("payment")
    if "minimum_age" in found or "account_termination_without_notice" in found:
        normal.remove("account_creation")
    return TermsProfile(
        document_hash=digest,
        clauses=list(found.values()),
        nothing_unusual=normal,
        partial=len(text) > 2_000_000,
    )


_PURPOSES = {
    "service_delivery": r"(?:provid|deliver|operat)\w*.{0,45}(?:service|product)|fulfil.{0,30}(?:order|contract)",
    "analytics": r"analytics|analy[sz].{0,40}(?:usage|traffic|use of|trends)",
    "personalised_ads": r"(?:personali[sz]ed|targeted|interest.based|behavio[u]?ral).{0,25}(?:ads|advertis)|advertising profiles",
    "marketing_email": r"(?:marketing|promotional).{0,25}(?:email|messages)|newsletters",
    "research": r"\bresearch\b",
    "legal": r"legal obligations|comply.{0,25}(?:law|legal)|regulatory requirements",
    "security": r"fraud|security|protect.{0,25}(?:account|service)",
    "product_improvement": r"improv.{0,30}(?:service|product|experience)",
    "ai_training": r"train.{0,50}(?:models|AI|artificial intelligence)|(?:machine learning|AI) training",
}
_SHARES = {
    "service_providers": r"service providers|processors|contractors",
    "advertising_partners": r"advertis(?:ing|ement)? (?:partners|networks|companies)|advertisers",
    "analytics_providers": r"analytics (?:providers|partners|companies|services)",
    "affiliates": r"affiliates|subsidiaries|group companies",
    "data_brokers": r"data brokers",
    "law_enforcement": r"law enforcement|government authorities|police",
    "buyers_on_acquisition": r"acquisition|merger|business transfer|buyer|purchaser",
}
_COLLECTS = {
    "full_name": r"\bnames?\b",
    "email": r"e.?mail (?:address|information)|\bemail\b",
    "phone": r"phone|telephone|mobile number",
    "postal_address": r"postal|mailing address|home address|street address",
    "dob": r"date of birth|birth date|\bdob\b",
    "age": r"\bage\b",
    "gender": r"gender|\bsex\b",
    "government_id": r"government.?id|identity document",
    "government_id.passport": r"passport",
    "financial.card_number": r"card number|credit card|payment card",
    "medical": r"medical|health information",
    "location_precise": r"precise location|GPS|exact location|geolocation",
    "location_coarse": r"approximate location|coarse location|city.level|general location",
    "device_identifiers": r"device (?:information|identifier|ID)|IP address|advertising ID",
    "browsing_activity": r"browsing (?:activity|history|behavior)|pages you visit|websites you visit",
    "contacts": r"address book|your contacts",
    "biometric_photo": r"biometric|facial recognition",
    "employment": r"employment|occupation",
    "education": r"education|qualifications",
}


def _positive_labels(sentence: str, rules: dict[str, str]) -> list[str]:
    labels = []
    for label, pattern in rules.items():
        for match in re.finditer(pattern, sentence, re.I):
            prefix = sentence[: match.start()]
            if re.search(
                r"\b(?:do not|does not|will not|never|no|not|without)\b[^,;.]{0,100}$", prefix, re.I
            ):
                continue
            labels.append(label)
            break
    return labels


def analyze_policy(text: str, purpose: str = "unknown") -> PolicyProfile:
    segmented = sentences(text[:2_000_000])
    terms = _terms_from_sentences(text, segmented)
    profile = PolicyProfile(
        document_hash=terms.document_hash,
        clauses=terms.clauses,
        missing=terms.missing,
        partial=terms.partial,
    )
    if terms.missing:
        profile.warnings.append("No privacy policy found")
        return profile
    collects: set[DataCategory] = set()
    used: set[str] = set()
    shares: set[str] = set()
    rights: set[str] = set()
    for sentence, heading in segmented:
        lower = sentence.lower()
        used.update(_positive_labels(sentence, _PURPOSES))
        if re.search(
            r"shar|disclos|provid|transfer|recipient|sold|sell|partner", lower
        ) or re.search(r"shar|disclos|recipient", heading, re.I):
            shares.update(_positive_labels(sentence, _SHARES))
        if re.search(
            r"collect|gather|obtain|receiv|process|information|data|access", lower
        ) or re.search(r"collect|information", heading, re.I):
            collects.update(DataCategory(label) for label in _positive_labels(sentence, _COLLECTS))
        for right, pattern in {
            "access": "right.{0,30}access|request.{0,30}copy",
            "deletion": "right.{0,30}(?:delet|eras)|request.{0,30}delet",
            "correction": "right.{0,30}(?:correct|rectif)",
            "portability": "portability|portable format",
            "opt_out": "opt.out|unsubscribe",
            "withdraw_consent": "withdraw.{0,15}consent",
            "complaint": "right.{0,30}complain|lodge.{0,15}complaint",
        }.items():
            if re.search(pattern, lower):
                rights.add(right)
        if re.search(r"children|minors|under.{0,10}(?:13|16|18)", lower):
            profile.children = redact_text(sentence)[:500]
        if re.search(r"contact|privacy officer|data protection officer", lower):
            profile.contact = redact_text(sentence)[:500]
        period = re.search(
            r"(?:retain|keep|store).{0,50}?((?:\d+|one|two|three|five|seven|ten)\s+(?:days?|months?|years?))",
            lower,
        )
        if period:
            profile.retention = "stated_period"
            profile.retention_period = period.group(1)
        if re.search(
            r"(?:until|upon|on).{0,40}(?:delet|clos).{0,25}(?:account)?|delet.{0,40}(?:upon|on).{0,30}(?:request|closure)",
            lower,
        ):
            profile.retention = "until_deletion"
    clause_names = {clause.category for clause in terms.clauses}
    if "retention_after_deletion" in clause_names:
        profile.retention = "after_deletion"
    if "training_on_user_content" in clause_names:
        used.add("ai_training")
    profile.international_transfer = "cross_border_transfer" in clause_names
    profile.collects = sorted(collects, key=str)
    profile.purposes = sorted(used)
    profile.shares_with = sorted(shares)
    profile.user_rights = sorted(rights)
    profile.necessity_statements = [
        f"Collects {category_label(category.value)}: {necessity_for(purpose, category).rationale}"
        for category in profile.collects
    ]
    return profile
