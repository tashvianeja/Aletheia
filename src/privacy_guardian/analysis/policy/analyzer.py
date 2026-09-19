from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field

from privacy_guardian.analysis.pii import redact_text
from privacy_guardian.core.events import DataCategory
from privacy_guardian.engine.labels import article, category_label, lowered, purpose_label
from privacy_guardian.engine.necessity import Necessity, necessity_for


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
    # The categories the policy claims that this kind of service has no evident use for,
    # kept as data so the report can say it once rather than string-matching sentences.
    over_collection: list[DataCategory] = Field(default_factory=list)
    missing: bool = False
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def patterns() -> dict[str, dict[str, list[str]]]:
    value: dict[str, dict[str, list[str]]] = json.loads(
        files("privacy_guardian.analysis.policy").joinpath("patterns/clauses.yaml").read_text()
    )
    return value


class _Rule(NamedTuple):
    positive: list[re.Pattern[str]]
    negative: list[re.Pattern[str]]
    # The clause's own subject matter. A pattern can only tell you what a sentence means
    # if the sentence is about the thing the clause is named after: "cancel at least 14
    # days before renewal" is not an age requirement, however close a number sits to
    # "at least". Every clause has to see its own subject before it may claim a sentence.
    requires: list[re.Pattern[str]]
    scope: list[str]


@lru_cache(maxsize=1)
def _compiled() -> dict[str, _Rule]:
    return {
        key: _Rule(
            [re.compile(pattern, re.I) for pattern in item["positive"]],
            [re.compile(pattern, re.I) for pattern in item["negative"]],
            [re.compile(pattern, re.I) for pattern in item.get("requires", [])],
            list(item["scope"]),
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


def _claims(sentence: str, rule: _Rule) -> bool:
    """Whether this sentence really is the clause, rather than merely resembling it."""
    if rule.requires and not any(pattern.search(sentence) for pattern in rule.requires):
        return False
    if any(pattern.search(sentence) for pattern in rule.negative):
        return False
    return any(pattern.search(sentence) for pattern in rule.positive)


def analyze_terms(text: str) -> TermsProfile:
    return _terms_from_sentences(text, sentences(text[:2_000_000]))


def _terms_from_sentences(text: str, segmented: list[tuple[str, str]]) -> TermsProfile:
    digest = hashlib.sha256(text.encode()).hexdigest()
    if not text.strip():
        return TermsProfile(document_hash=digest, missing=True, nothing_unusual=[])
    found: dict[str, Clause] = {}
    for sentence, heading in segmented:
        for category, rule in _compiled().items():
            if not _claims(sentence, rule):
                continue
            confidence = (
                0.96 if any(scope.lower() in heading.lower() for scope in rule.scope) else 0.9
            )
            existing = found.get(category)
            # The first sentence that matches is not always the one worth quoting. A
            # cancellation notice and a real age limit can both mention a small number;
            # the sentence under the matching heading is the one that means it.
            if existing is not None and existing.confidence >= confidence:
                continue
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
    "age": r"\bages?\b",
    "gender": r"gender|\bsex\b",
    "government_id": r"government.?(?:issued )?id|identity document|identification (?:number|document)",
    "government_id.passport": r"passport",
    "financial.card_number": r"card number|credit card|payment card",
    "medical": r"medical (?:history|records?|information|conditions?|data)|health (?:information|data|records?|conditions?)|\bdiagnos(?:is|es|ed)\b|\bprescriptions?\b|\bmedications?\b",
    "location_precise": r"precise location|GPS|exact location|geolocation",
    "location_coarse": r"approximate location|coarse location|city.level|general location",
    "device_identifiers": r"device (?:information|identifier|ID)|IP address|advertising ID",
    "browsing_activity": r"browsing (?:activity|history|behavior)|pages you visit|websites you visit",
    "contacts": r"address book|your contacts",
    "biometric_photo": r"biometric|facial recognition",
    "employment": r"employment (?:history|status|information|details|records?)|\bjob title\b|\boccupation\b|your employer|professional (?:title|background)",
    "education": r"education(?:al)? (?:history|background|qualifications?|records?|details?|information|level|institution)|\bdegrees?\b|\bqualifications\b|school you attend",
}
# The same word, a few words earlier, means something that is not you: a domain name, a
# file name, the course of employment, educational purposes, a clause promising not to
# discriminate on the basis of sex. A hit inside one of these is not a collection claim.
_NOT_ABOUT_YOU = {
    "full_name": r"(?:domain|file|host|device|brand|product|company|business|trade|screen|display|folder|path|street|user|pet|sub)\s*names?|names?\s+(?:of|for)\b",
    "age": r"age of (?:consent|majority)",
    "gender": r"regardless of|discriminat|equal opportunit|on the basis of",
    "employment": r"course of employment|employment (?:agency|law|relationship|practices)",
    "education": r"educational purposes",
    "medical": r"medical (?:device|advice|emergency)|diagnostics?",
}
# The verbs a policy uses when it is telling you what it takes. A sentence carrying none
# of them is describing something else — what a word means, who owns the trademarks, who
# the company does not discriminate against — and reading a list of data categories out
# of it is how a check comes to report collection that never happens.
_COLLECTION_VERB = re.compile(
    r"\b(?:collect|gather|obtain|receiv|request|ask|stor|retain|log|record|captur|"
    r"hold|maintain|keep|requir|submit)\w*",
    re.I,
)
# "We use browsing activity for advertising" says what they do with it, not that they
# took it, and reporting the two the same way is how a check ends up asserting more than
# the document does. These verbs open a claim only where a list follows them.
_HANDLING_VERB = re.compile(r"\b(?:process|use|using|shar|sell|disclos|transfer)\w*", re.I)
# Where a policy names the things it takes. "Technical information such as your IP
# address" names an IP address; the words in front of "such as" name nothing.
_ENUMERATION = re.compile(
    r"(?:such as|including(?: but not limited to)?|includes?|for example|e\.g\.|:)", re.I
)
# A bullet list under "Information we collect" is a collection statement even though the
# line itself is only a noun.
_COLLECTION_HEADING = re.compile(
    r"(?:information|data|details)\s+(?:that\s+|which\s+)?we\s+"
    r"(?:collect|gather|obtain|receive|process)|what we collect|"
    r"(?:personal|categories of)\s+(?:information|data)|information (?:you|we)",
    re.I,
)
_NEGATION = re.compile(r"\b(?:do not|does not|will not|never|no|not|without)\b[^,;.]{0,100}$", re.I)


def _collection_span(sentence: str, heading: str) -> tuple[int, int] | None:
    """The part of a sentence that names what is taken, or None if it names nothing."""
    if _COLLECTION_HEADING.search(heading):
        return 0, len(sentence)
    verb = _COLLECTION_VERB.search(sentence)
    handling = _HANDLING_VERB.search(sentence) if verb is None else None
    if verb is None and handling is None:
        return None
    start = (verb or handling).end()  # type: ignore[union-attr]
    last = None
    for match in _ENUMERATION.finditer(sentence, start):
        last = match
    if last is None:
        return (start, len(sentence)) if verb is not None else None
    return last.end(), len(sentence)


def collected_categories(sentence: str, heading: str = "") -> set[str]:
    """The data categories this sentence actually says are collected."""
    span = _collection_span(sentence, heading)
    if span is None:
        return set()
    start, end = span
    found: set[str] = set()
    for label, pattern in _COLLECTS.items():
        for match in re.finditer(pattern, sentence[start:end], re.I):
            at = start + match.start()
            if _NEGATION.search(sentence[:at]):
                continue
            disqualifier = _NOT_ABOUT_YOU.get(label)
            window = sentence[max(0, at - 40) : start + match.end() + 40]
            if disqualifier and re.search(disqualifier, window, re.I):
                continue
            found.add(label)
            break
    return found


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


def collection_statements(collects: list[DataCategory], purpose: str) -> list[str]:
    """What the policy says it takes, said the way a person would say it.

    The old sentence named the category twice and then quoted the necessity engine at
    the reader: "Collects Date of birth: Date of birth does not appear necessary for a
    file converter." One category, one plain sentence, and the judgement at the end
    where it can be disagreed with.
    """
    named = purpose_label(purpose)
    statements: list[str] = []
    for category in collects:
        thing = lowered(category_label(category.value))
        verdict = necessity_for(purpose, category).verdict
        if purpose == "unknown":
            statements.append(f"The policy says it collects your {thing}.")
        elif verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}:
            statements.append(
                f"The policy says it collects your {thing}, "
                f"which {article(named)} {named} does not appear to need."
            )
        elif verdict is Necessity.REQUIRED:
            statements.append(
                f"The policy says it collects your {thing}, which {article(named)} {named} needs."
            )
        else:
            statements.append(f"The policy says it collects your {thing}.")
    return statements


def over_collected(collects: list[DataCategory], purpose: str) -> list[DataCategory]:
    """The categories a service of this kind has no evident use for."""
    if purpose == "unknown":
        return []
    return [
        category
        for category in collects
        if necessity_for(purpose, category).verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}
    ]


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
        collects.update(DataCategory(label) for label in collected_categories(sentence, heading))
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
    profile.necessity_statements = collection_statements(profile.collects, purpose)
    profile.over_collection = over_collected(profile.collects, purpose)
    return profile
