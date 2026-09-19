from __future__ import annotations

from functools import lru_cache
from importlib.resources import as_file, files

import numpy as np
from pydantic import BaseModel, Field

from privacy_guardian.core.events import DataCategory, FormContext, FormField
from privacy_guardian.intelligence.embedder import embed_one
from privacy_guardian.intelligence.taxonomy import FormIntent

# Structural evidence is deterministic and near-certain where it fires: a `cc-number`
# field means payment whatever the marketing copy says. Sentence similarity generalises
# to the wording and language the site actually used. Neither is sufficient alone, so
# both are accumulated as log-odds and normalised together.
_EMBED_TEMPERATURE = 0.09
_EMBED_WEIGHT = 2.2


class Structure(BaseModel):
    """Machine-readable shape of a form, independent of its prose."""

    field_count: int = 0
    autocomplete: set[str] = Field(default_factory=set)
    categories: set[DataCategory] = Field(default_factory=set)
    current_password: bool = False
    new_password: bool = False
    password_count: int = 0
    one_time_code: bool = False
    card: bool = False
    shipping_section: bool = False
    billing_section: bool = False
    textarea: bool = False
    file_upload: bool = False
    search_box: bool = False
    identifiers: int = 0
    required_count: int = 0


def describe(fields: list[FormField]) -> Structure:
    tokens: set[str] = set()
    for field in fields:
        tokens |= {token for token in field.autocomplete.lower().replace("-", "-").split() if token}
    categories = {field.category for field in fields if field.category is not None}
    passwords = [field for field in fields if field.input_type == "password"]
    short_numeric = any(
        0 < field.max_length <= 8
        and (field.input_type in {"tel", "number", "text"})
        and _looks_like_code(field)
        for field in fields
    )
    return Structure(
        field_count=len(fields),
        autocomplete=tokens,
        categories=categories,
        current_password="current-password" in tokens,
        new_password="new-password" in tokens,
        password_count=len(passwords),
        one_time_code="one-time-code" in tokens or short_numeric,
        card=bool(tokens & {"cc-number", "cc-csc", "cc-exp", "cc-exp-month", "cc-exp-year"})
        or DataCategory.FINANCIAL_CARD_NUMBER in categories,
        shipping_section="shipping" in tokens,
        billing_section="billing" in tokens,
        textarea=any(field.input_type in {"textarea", "contenteditable"} for field in fields),
        file_upload=any(field.input_type == "file" for field in fields),
        search_box=any(field.input_type == "search" for field in fields),
        identifiers=sum(
            field.category in {DataCategory.EMAIL, DataCategory.PHONE} for field in fields
        )
        + sum(_is_username(field) for field in fields),
        required_count=sum(field.required or field.asserted_required for field in fields),
    )


def _looks_like_code(field: FormField) -> bool:
    text = " ".join((field.label, field.name, field.field_id)).lower()
    return any(word in text for word in ("code", "otp", "passcode", "verification", "token", "pin"))


def _is_username(field: FormField) -> bool:
    if field.category is not None:
        return False
    text = " ".join((field.label, field.name, field.field_id, field.autocomplete)).lower()
    return "username" in text or "user name" in text or text.strip() in {"user", "login", "handle"}


def structural_evidence(structure: Structure) -> dict[FormIntent, float]:
    """Log-odds contributions from form shape alone."""
    score = dict.fromkeys(FormIntent, 0.0)
    s = structure
    if s.card:
        score[FormIntent.CHECKOUT_PAYMENT] += 4.0
    if s.one_time_code and s.password_count == 0:
        score[FormIntent.TWO_FACTOR] += 4.0
    if s.current_password and not s.new_password:
        # A login is the single most common form on the web and the one where a false
        # "your password is unnecessary" warning does the most damage to trust.
        score[FormIntent.ACCOUNT_LOGIN] += 3.8
    if s.new_password and s.current_password:
        score[FormIntent.PROFILE_EDIT] += 2.4
    if s.new_password and not s.current_password:
        if s.identifiers or DataCategory.FULL_NAME in s.categories:
            score[FormIntent.ACCOUNT_SIGNUP] += 3.0
        else:
            score[FormIntent.PASSWORD_RESET] += 3.0
    if s.password_count >= 2 and not s.current_password:
        score[FormIntent.ACCOUNT_SIGNUP] += 1.0
        score[FormIntent.PASSWORD_RESET] += 1.0
    if s.password_count == 0 and s.field_count <= 2 and DataCategory.EMAIL in s.categories:
        score[FormIntent.NEWSLETTER] += 2.2
    if s.textarea and DataCategory.EMAIL in s.categories:
        score[FormIntent.CONTACT_SUPPORT] += 2.2
    if s.file_upload and (DataCategory.EMAIL in s.categories or DataCategory.PHONE in s.categories):
        score[FormIntent.JOB_APPLICATION] += 2.0
    if s.shipping_section:
        score[FormIntent.SHIPPING_ADDRESS] += 3.0
    elif (
        DataCategory.POSTAL_ADDRESS in s.categories
        and s.password_count == 0
        and not s.card
        # Nobody needs a date of birth to post a parcel, so its presence argues that this
        # address is being collected for some other reason.
        and DataCategory.DOB not in s.categories
    ):
        score[FormIntent.SHIPPING_ADDRESS] += 1.6
    if s.billing_section:
        score[FormIntent.CHECKOUT_PAYMENT] += 1.5
    if {category for category in s.categories if category.value.startswith("government_id")}:
        score[FormIntent.IDENTITY_VERIFICATION] += 2.6
    if s.search_box and s.field_count <= 2:
        score[FormIntent.SEARCH_FILTER] += 3.5
    if s.password_count == 0 and not s.card and DataCategory.EMAIL in s.categories:
        # Contact details with nothing to sign into and nothing to pay for is the shape
        # of a form that exists to collect the details rather than to do something.
        if s.field_count >= 4:
            score[FormIntent.LEAD_CAPTURE] += 0.9
        if s.field_count >= 6:
            score[FormIntent.LEAD_CAPTURE] += 0.6
            score[FormIntent.SURVEY_FEEDBACK] += 0.4
    return score


@lru_cache(maxsize=1)
def _centroids() -> tuple[tuple[FormIntent, ...], np.ndarray] | None:
    try:
        with as_file(
            files("privacy_guardian.data.models").joinpath("intent_centroids.npz")
        ) as path:
            if not path.exists():
                return None
            with np.load(path, allow_pickle=False) as data:
                names = tuple(FormIntent(str(name)) for name in data["names"])
                return names, np.asarray(data["centroids"], dtype=np.float32)
    except (ModuleNotFoundError, FileNotFoundError, OSError, ValueError, KeyError):
        return None


def context_text(context: FormContext) -> str:
    parts = [
        context.heading,
        context.legend,
        context.submit_text,
        context.nearby_text,
        context.page_title,
    ]
    return " . ".join(part.strip() for part in parts if part and part.strip())[:600]


def semantic_evidence(context: FormContext) -> dict[FormIntent, float]:
    text = context_text(context)
    loaded = _centroids()
    if not text or loaded is None:
        return {}
    vector = embed_one(text)
    if vector is None:
        return {}
    names, matrix = loaded
    sims = matrix @ vector
    centred = (sims - float(sims.mean())) / _EMBED_TEMPERATURE
    return {
        name: _EMBED_WEIGHT * float(np.clip(value, -4.0, 4.0))
        for name, value in zip(names, centred, strict=True)
    }


# What a site's line of business suggests its forms are for. A weak prior by design:
# it breaks ties on forms whose shape and prose are ambiguous, and is outweighed by any
# real structural evidence, so a bank's newsletter box is still a newsletter box.
_PURPOSE_PRIOR: dict[str, dict[FormIntent, float]] = {
    "free_download": {FormIntent.LEAD_CAPTURE: 1.6, FormIntent.NEWSLETTER: 0.6},
    "recipe": {FormIntent.NEWSLETTER: 1.2, FormIntent.LEAD_CAPTURE: 0.8},
    "news": {FormIntent.NEWSLETTER: 1.4, FormIntent.LEAD_CAPTURE: 0.6},
    "wallpaper_utility": {FormIntent.LEAD_CAPTURE: 1.4},
    "image_tool": {FormIntent.LEAD_CAPTURE: 1.2},
    "file_converter": {FormIntent.LEAD_CAPTURE: 1.2},
    "saas_b2b": {FormIntent.LEAD_CAPTURE: 1.0, FormIntent.ACCOUNT_SIGNUP: 0.5},
    "ecommerce": {FormIntent.CHECKOUT_PAYMENT: 0.9, FormIntent.SHIPPING_ADDRESS: 0.9},
    "food_delivery": {FormIntent.SHIPPING_ADDRESS: 1.0, FormIntent.CHECKOUT_PAYMENT: 0.8},
    "shopping_comparison": {FormIntent.NEWSLETTER: 0.8},
    "banking": {FormIntent.IDENTITY_VERIFICATION: 1.0, FormIntent.ACCOUNT_LOGIN: 0.6},
    "finance_investing": {FormIntent.IDENTITY_VERIFICATION: 1.0},
    "insurance": {FormIntent.IDENTITY_VERIFICATION: 0.8, FormIntent.LEAD_CAPTURE: 0.6},
    "government": {FormIntent.IDENTITY_VERIFICATION: 1.2},
    "healthcare_provider": {FormIntent.IDENTITY_VERIFICATION: 0.8, FormIntent.BOOKING: 0.8},
    "job_board": {FormIntent.JOB_APPLICATION: 1.4},
    "recruitment": {FormIntent.JOB_APPLICATION: 1.4},
    "social": {FormIntent.ACCOUNT_SIGNUP: 0.6, FormIntent.ACCOUNT_LOGIN: 0.6},
    "dating": {FormIntent.ACCOUNT_SIGNUP: 0.8, FormIntent.PROFILE_EDIT: 0.6},
    "messaging": {FormIntent.ACCOUNT_SIGNUP: 0.6, FormIntent.ACCOUNT_LOGIN: 0.6},
    "gaming": {FormIntent.ACCOUNT_SIGNUP: 0.6},
    "travel_booking": {FormIntent.BOOKING: 1.2},
    "airline": {FormIntent.BOOKING: 1.2},
    "email": {FormIntent.ACCOUNT_LOGIN: 0.8},
    "search": {FormIntent.SEARCH_FILTER: 1.0},
}


class IntentResult(BaseModel):
    intent: FormIntent = FormIntent.UNKNOWN
    confidence: float = Field(default=0.0, ge=0, le=1)
    runner_up: FormIntent = FormIntent.UNKNOWN
    semantic: bool = False
    structure: Structure = Field(default_factory=Structure)


def classify_form(
    fields: list[FormField],
    context: FormContext | None = None,
    site_purpose: str = "unknown",
) -> IntentResult:
    context = context or FormContext()
    structure = describe(fields)
    scores = structural_evidence(structure)
    semantic = semantic_evidence(context)
    for intent, value in semantic.items():
        scores[intent] = scores.get(intent, 0.0) + value
    for intent, value in _PURPOSE_PRIOR.get(site_purpose, {}).items():
        scores[intent] = scores.get(intent, 0.0) + value
    candidates = {intent: value for intent, value in scores.items() if intent != FormIntent.UNKNOWN}
    if not candidates or max(candidates.values()) <= 0:
        return IntentResult(structure=structure, semantic=bool(semantic))
    order = sorted(candidates.items(), key=lambda item: -item[1])
    values = np.array([value for _, value in order], dtype=np.float64)
    weights = np.exp(values - values.max())
    probabilities = weights / weights.sum()
    return IntentResult(
        intent=order[0][0],
        confidence=float(probabilities[0]),
        runner_up=order[1][0] if len(order) > 1 else FormIntent.UNKNOWN,
        semantic=bool(semantic),
        structure=structure,
    )
