from __future__ import annotations

import re

from pydantic import BaseModel, Field

from aletheia.core.events import DataCategory, FormContext, FormField
from aletheia.engine.labels import category_label
from aletheia.engine.necessity import Necessity, NecessityAssessment
from aletheia.intelligence.intent import IntentResult, Structure, classify_form
from aletheia.intelligence.taxonomy import FieldRole, FormIntent

C = DataCategory
# Below this the form's intent is a guess, and a guess is not grounds for telling someone
# their data is unnecessary. Guessing wrong is what made the old model unusable.
MIN_INTENT_CONFIDENCE = 0.45

IDENTITY = {C.EMAIL, C.PHONE}
CONTACTABLE = {C.EMAIL, C.PHONE, C.POSTAL_ADDRESS}
SENSITIVE_ROOTS = {"government_id", "financial", "medical", "credentials", "biometric_photo"}

# Per intent: what the transaction genuinely needs, what it can defensibly use, and what
# is disproportionate enough to name. Anything unlisted falls through to `default`.
_REQUIRED: dict[FormIntent, set[DataCategory]] = {
    FormIntent.ACCOUNT_SIGNUP: {C.EMAIL, C.PHONE, C.CREDENTIALS_PASSWORD, C.CREDENTIALS},
    FormIntent.ACCOUNT_LOGIN: {C.EMAIL, C.PHONE, C.CREDENTIALS_PASSWORD, C.CREDENTIALS},
    FormIntent.PASSWORD_RESET: {C.EMAIL, C.PHONE, C.CREDENTIALS_PASSWORD, C.CREDENTIALS},
    FormIntent.TWO_FACTOR: {C.CREDENTIALS_PASSWORD, C.CREDENTIALS, C.PHONE},
    FormIntent.CHECKOUT_PAYMENT: {
        C.FINANCIAL,
        C.FINANCIAL_CARD_NUMBER,
        C.FINANCIAL_IBAN,
        C.FINANCIAL_ACCOUNT_NUMBER,
        C.FINANCIAL_ROUTING,
        C.FULL_NAME,
        C.POSTAL_ADDRESS,
        C.EMAIL,
    },
    FormIntent.SHIPPING_ADDRESS: {C.POSTAL_ADDRESS, C.FULL_NAME},
    FormIntent.NEWSLETTER: {C.EMAIL},
    FormIntent.LEAD_CAPTURE: {C.EMAIL},
    FormIntent.CONTACT_SUPPORT: {C.EMAIL, C.FULL_NAME, C.FREE_TEXT_PII},
    FormIntent.IDENTITY_VERIFICATION: {
        C.GOVERNMENT_ID,
        C.GOVERNMENT_ID_PASSPORT,
        C.GOVERNMENT_ID_NATIONAL_ID,
        C.GOVERNMENT_ID_DRIVERS_LICENSE,
        C.GOVERNMENT_ID_SSN,
        C.GOVERNMENT_ID_TAX_ID,
        C.FULL_NAME,
        C.DOB,
        C.POSTAL_ADDRESS,
    },
    FormIntent.JOB_APPLICATION: {C.FULL_NAME, C.EMAIL, C.EMPLOYMENT, C.EDUCATION},
    FormIntent.BOOKING: {C.FULL_NAME, C.EMAIL},
    FormIntent.PROFILE_EDIT: set(),
    FormIntent.SURVEY_FEEDBACK: set(),
    FormIntent.SEARCH_FILTER: set(),
}

_REASONABLE: dict[FormIntent, set[DataCategory]] = {
    # Age gating is a legal obligation for most platforms, and a recovery phone number is
    # a security feature. Neither is over-collection at the point of creating an account.
    FormIntent.ACCOUNT_SIGNUP: {C.FULL_NAME, C.DOB, C.AGE, C.LOCATION_COARSE},
    FormIntent.ACCOUNT_LOGIN: set(),
    FormIntent.PASSWORD_RESET: {C.FULL_NAME},
    FormIntent.TWO_FACTOR: {C.EMAIL},
    FormIntent.CHECKOUT_PAYMENT: {C.PHONE, C.DOB, C.AGE, C.LOCATION_COARSE},
    FormIntent.SHIPPING_ADDRESS: {C.PHONE, C.EMAIL, C.LOCATION_COARSE},
    FormIntent.NEWSLETTER: {C.FULL_NAME},
    FormIntent.LEAD_CAPTURE: {C.FULL_NAME, C.EMPLOYMENT},
    FormIntent.CONTACT_SUPPORT: {C.PHONE},
    FormIntent.IDENTITY_VERIFICATION: {
        C.PHONE,
        C.EMAIL,
        C.BIOMETRIC_PHOTO,
        C.AGE,
        C.GENDER,
        C.FINANCIAL,
        C.FINANCIAL_ACCOUNT_NUMBER,
    },
    FormIntent.JOB_APPLICATION: {C.PHONE, C.POSTAL_ADDRESS, C.FREE_TEXT_PII, C.LOCATION_COARSE},
    # An airline really does need a passport, and a clinic really does need a diagnosis.
    FormIntent.BOOKING: {
        C.PHONE,
        C.POSTAL_ADDRESS,
        C.DOB,
        C.AGE,
        C.GENDER,
        C.GOVERNMENT_ID,
        C.GOVERNMENT_ID_PASSPORT,
        C.FINANCIAL,
        C.FINANCIAL_CARD_NUMBER,
    },
    FormIntent.PROFILE_EDIT: {
        C.FULL_NAME,
        C.EMAIL,
        C.PHONE,
        C.DOB,
        C.AGE,
        C.GENDER,
        C.POSTAL_ADDRESS,
        C.EMPLOYMENT,
        C.EDUCATION,
        C.LOCATION_COARSE,
        C.BIOMETRIC_PHOTO,
        C.FREE_TEXT_PII,
    },
    FormIntent.SURVEY_FEEDBACK: {C.EMAIL, C.AGE, C.GENDER, C.LOCATION_COARSE, C.FREE_TEXT_PII},
    FormIntent.SEARCH_FILTER: {C.LOCATION_COARSE},
}

# Categories a given intent has no business touching at all.
_RED_FLAG: dict[FormIntent, set[DataCategory]] = {
    FormIntent.NEWSLETTER: {
        C.GOVERNMENT_ID,
        C.FINANCIAL,
        C.MEDICAL,
        C.ETHNICITY_RELIGION_ORIENTATION,
    },
    FormIntent.LEAD_CAPTURE: {C.GOVERNMENT_ID, C.FINANCIAL, C.MEDICAL},
    FormIntent.SEARCH_FILTER: {C.GOVERNMENT_ID, C.FINANCIAL, C.MEDICAL, C.CREDENTIALS},
    FormIntent.SURVEY_FEEDBACK: {C.GOVERNMENT_ID, C.FINANCIAL, C.MEDICAL},
    # Asking for identity documents or bank details before an interview is a known
    # recruitment-fraud pattern, and date of birth invites age discrimination.
    FormIntent.JOB_APPLICATION: {C.GOVERNMENT_ID, C.FINANCIAL, C.MEDICAL},
    FormIntent.CONTACT_SUPPORT: {C.GOVERNMENT_ID, C.FINANCIAL},
    FormIntent.ACCOUNT_LOGIN: {C.GOVERNMENT_ID, C.FINANCIAL, C.MEDICAL},
}

# Sites whose stated business makes sensitive collection ordinary, and sites where the
# same request has no plausible explanation. This is the site-purpose signal, kept as a
# modifier on top of intent rather than as the basis of the judgement.
_PLAUSIBLE_SENSITIVE = {
    "banking": {"financial", "government_id"},
    "finance_investing": {"financial", "government_id"},
    "insurance": {"financial", "government_id", "medical"},
    "government": {"government_id", "financial", "medical"},
    "healthcare_provider": {"medical", "government_id", "financial"},
    "fitness": {"medical"},
    "legal_services": {"government_id"},
    "recruitment": {"government_id"},
    "job_board": {"government_id"},
    "airline": {"government_id"},
    "travel_booking": {"government_id"},
    "ecommerce": {"financial"},
    "food_delivery": {"financial"},
    "ride_hailing": {"financial"},
    "dating": {"government_id", "biometric_photo"},
}
_IMPLAUSIBLE_RECIPIENTS = {
    "image_tool",
    "file_converter",
    "wallpaper_utility",
    "recipe",
    "news",
    "weather",
    "free_download",
    "screen_recorder",
    "search",
    "music_streaming",
    "video_streaming",
    "gaming",
}

_DISJUNCTION = re.compile(r"\b(?:or|ou|oder|o|of)\b|/", re.I)


_PAYMENT_INTENTS = {
    FormIntent.CHECKOUT_PAYMENT,
    FormIntent.BOOKING,
    FormIntent.IDENTITY_VERIFICATION,
    FormIntent.PROFILE_EDIT,
}
# The forms that have a password to take: there is an account to get into, or one to
# make. Everywhere else a password box is somebody asking for the keys to something
# they have nothing to do with.
_AUTH_INTENTS = {
    FormIntent.ACCOUNT_SIGNUP,
    FormIntent.ACCOUNT_LOGIN,
    FormIntent.PASSWORD_RESET,
    FormIntent.TWO_FACTOR,
    FormIntent.PROFILE_EDIT,
}


def credential_expected(field: FormField, intent: FormIntent, structure: Structure) -> bool:
    """Whether this form has any business holding a password.

    Never telling someone their password is unnecessary protects the one case that
    matters — a login — by silencing the other one, where a survey asks for the password
    to an account it has nothing to do with. The question is not whether the field is a
    password; it is whether there is anything here to sign in to.
    """
    if intent in _AUTH_INTENTS:
        return True
    if intent is FormIntent.UNKNOWN:
        # A form nobody could classify, carrying a real masked password box, is a sign-in
        # far more often than it is an attack. A question typed in the clear is not.
        return field.input_type == "password" and structure.password_count > 0
    return False


def _root(category: DataCategory) -> str:
    return category.value.split(".")[0]


def _matches(category: DataCategory, group: set[DataCategory]) -> bool:
    if category in group:
        return True
    # A parent listed in the table covers its refinements: `financial` covers `financial.iban`.
    return any(item.value == _root(category) for item in group)


def _is_alternate_identifier(field: FormField) -> bool:
    """True for a single box that accepts either of two identifiers.

    Instagram's "Mobile Number or Email" is one field standing in for two, and reading it
    as a demand for a phone number is how the old model came to call the single most
    necessary field on the page unnecessary.
    """
    text = field.label.lower()
    if not text:
        return False
    hits = sum(
        bool(re.search(pattern, text))
        for pattern in (
            r"e.?mail|correo|courriel",
            r"phone|mobile|tel|handy|m[oó]vil",
            r"user.?name",
        )
    )
    return hits >= 2 and bool(_DISJUNCTION.search(text))


def infer_role(
    field: FormField, intent: FormIntent, structure: Structure, verdict: Necessity
) -> FieldRole:
    category = field.category
    if category is None:
        return FieldRole.PROFILE_DETAIL
    root = _root(category)
    if root == "credentials":
        if credential_expected(field, intent, structure):
            return FieldRole.CREDENTIAL
        return FieldRole.UNRELATED_COLLECTION
    # A card number is a payment instrument on a form that takes payment. On a job
    # application it is just a bank account somebody has asked a stranger for, and
    # calling it a payment instrument is what would hide it.
    if root == "financial" and intent in _PAYMENT_INTENTS:
        return FieldRole.PAYMENT_INSTRUMENT
    if intent is FormIntent.IDENTITY_VERIFICATION and (
        root == "government_id" or category in {C.DOB, C.BIOMETRIC_PHOTO}
    ):
        return FieldRole.VERIFICATION_EVIDENCE
    if (
        intent
        in {
            FormIntent.ACCOUNT_SIGNUP,
            FormIntent.ACCOUNT_LOGIN,
            FormIntent.PASSWORD_RESET,
        }
        and category in IDENTITY
    ):
        if _is_alternate_identifier(field) or structure.identifiers > 1:
            return FieldRole.ALTERNATE_IDENTIFIER
        return FieldRole.PRIMARY_IDENTIFIER
    if intent in {FormIntent.SHIPPING_ADDRESS, FormIntent.CHECKOUT_PAYMENT} and category in {
        C.POSTAL_ADDRESS,
        C.FULL_NAME,
    }:
        return FieldRole.DELIVERY_TARGET
    if category in CONTACTABLE and verdict in {Necessity.REQUIRED, Necessity.REASONABLE}:
        return FieldRole.CONTACT_CHANNEL
    if verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}:
        if not (field.required or field.asserted_required):
            return FieldRole.MARKETING_OPTIONAL
        return FieldRole.UNRELATED_COLLECTION
    return FieldRole.PROFILE_DETAIL


def _verifies_identity(site_purpose: str) -> bool:
    return bool(_PLAUSIBLE_SENSITIVE.get(site_purpose, set()) & {"government_id", "medical"})


def verdict_for(
    category: DataCategory,
    intent: FormIntent,
    *,
    site_purpose: str = "unknown",
    intent_confidence: float = 1.0,
    expected_credential: bool = True,
) -> Necessity:
    root = _root(category)
    if intent is FormIntent.UNKNOWN or intent_confidence < MIN_INTENT_CONFIDENCE:
        # Nothing is known about the transaction, so only an implausible recipient of
        # genuinely sensitive data is worth saying anything about. A password typed into
        # a box that does not hide it, on a page with no sign-in, is one of those.
        watched = SENSITIVE_ROOTS if not expected_credential else SENSITIVE_ROOTS - {"credentials"}
        if root in watched:
            if site_purpose in _IMPLAUSIBLE_RECIPIENTS:
                return Necessity.RED_FLAG
            if root not in _PLAUSIBLE_SENSITIVE.get(site_purpose, set()):
                # Unattributed, but the site has no stated business needing it either.
                return Necessity.UNNECESSARY
        return Necessity.REASONABLE
    if _matches(category, _RED_FLAG.get(intent, set())):
        verdict = Necessity.RED_FLAG
    elif _matches(category, _REQUIRED.get(intent, set())):
        verdict = Necessity.REQUIRED
    elif _matches(category, _REASONABLE.get(intent, set())):
        verdict = Necessity.REASONABLE
    elif root in SENSITIVE_ROOTS:
        verdict = Necessity.RED_FLAG
    else:
        verdict = Necessity.UNNECESSARY
    if root in SENSITIVE_ROOTS and verdict in {Necessity.UNNECESSARY, Necessity.RED_FLAG}:
        if root in _PLAUSIBLE_SENSITIVE.get(site_purpose, set()):
            # The site's business explains the request even when the form's shape does not.
            verdict = Necessity.REASONABLE
        elif site_purpose in _IMPLAUSIBLE_RECIPIENTS:
            verdict = Necessity.RED_FLAG
    return verdict


# How each intent reads inside "X is not needed to <phrase>".
INTENT_PHRASES: dict[FormIntent, str] = {
    FormIntent.ACCOUNT_SIGNUP: "create an account",
    FormIntent.ACCOUNT_LOGIN: "sign in",
    FormIntent.PASSWORD_RESET: "reset a password",
    FormIntent.TWO_FACTOR: "confirm a sign-in code",
    FormIntent.CHECKOUT_PAYMENT: "pay for an order",
    FormIntent.SHIPPING_ADDRESS: "deliver an order",
    FormIntent.NEWSLETTER: "join a mailing list",
    FormIntent.LEAD_CAPTURE: "get this",
    FormIntent.CONTACT_SUPPORT: "send a message",
    FormIntent.PROFILE_EDIT: "update a profile",
    FormIntent.IDENTITY_VERIFICATION: "verify identity",
    FormIntent.JOB_APPLICATION: "apply for a job",
    FormIntent.BOOKING: "make a booking",
    FormIntent.SURVEY_FEEDBACK: "answer a survey",
    FormIntent.SEARCH_FILTER: "run a search",
}

# Extra context where the plain sentence understates why it matters.
_CAVEATS: dict[tuple[FormIntent, str], str] = {
    (FormIntent.JOB_APPLICATION, "dob"): "Employers rarely need it before an offer.",
    (FormIntent.JOB_APPLICATION, "government_id"): (
        "Identity documents are normally collected after an offer, not with an application."
    ),
    (FormIntent.JOB_APPLICATION, "financial"): (
        "Bank details before an offer are a common recruitment scam."
    ),
    (FormIntent.LEAD_CAPTURE, "phone"): "A phone number here usually means a sales call.",
    (FormIntent.NEWSLETTER, "phone"): "An email address is all a mailing list needs.",
    (FormIntent.NEWSLETTER, "postal_address"): "A mailing list is delivered to your inbox.",
    (FormIntent.NEWSLETTER, "dob"): "A mailing list does not depend on your age.",
}

# Below this, over-collection is not worth interrupting anyone about. Email and full name
# on a form you chose to fill in are not news; a passport number is.
SENSITIVITY_FLOOR = 0.45


def _worth_naming(category: DataCategory) -> bool:
    from aletheia.engine.classifier import load_sensitivities

    return load_sensitivities().get(category.value, 0.0) >= SENSITIVITY_FLOOR


def explain_field(
    category: DataCategory, intent: FormIntent, verdict: Necessity, role: FieldRole
) -> str:
    label = category_label(category.value)
    phrase = INTENT_PHRASES.get(intent, "")
    if role in {FieldRole.PRIMARY_IDENTIFIER, FieldRole.ALTERNATE_IDENTIFIER}:
        return f"{label} is how this account is identified."
    if verdict is Necessity.REQUIRED:
        return f"{label} is needed to {phrase}." if phrase else f"{label} is needed here."
    if verdict is Necessity.REASONABLE:
        return (
            f"{label} is a normal thing to ask when you {phrase}."
            if phrase
            else f"{label} is a normal thing to ask here."
        )
    root = _root(category)
    if root == "credentials":
        # The single most valuable thing this product can say, so it does not hide
        # behind "does not appear necessary for a survey".
        return (
            f"{label}: there is nothing to sign in to here. "
            "A form that asks for it is asking for the keys to an account it does not run."
        )
    caveat = _CAVEATS.get((intent, root), "")
    if not phrase:
        base = f"{label} does not appear necessary here."
    elif verdict is Necessity.RED_FLAG:
        base = f"{label} is unusually sensitive and is not needed to {phrase}."
    else:
        base = f"{label} is not needed to {phrase}."
    return f"{base} {caveat}".strip()


class FieldJudgement(BaseModel):
    field: FormField
    role: FieldRole
    verdict: Necessity
    confidence: float = Field(default=0.0, ge=0, le=1)
    rationale: str = ""
    flag: bool = False


class FormJudgement(BaseModel):
    intent: IntentResult = Field(default_factory=IntentResult)
    fields: list[FieldJudgement] = Field(default_factory=list)
    site_purpose: str = "unknown"

    @property
    def flagged(self) -> list[FieldJudgement]:
        return [item for item in self.fields if item.flag]


# Roles that exist because the person asked for the transaction. Naming one of these as
# unnecessary is always wrong, whatever the tables say.
_NEVER_FLAG = {
    FieldRole.PRIMARY_IDENTIFIER,
    FieldRole.ALTERNATE_IDENTIFIER,
    FieldRole.CREDENTIAL,
    FieldRole.PAYMENT_INSTRUMENT,
    FieldRole.DELIVERY_TARGET,
    FieldRole.VERIFICATION_EVIDENCE,
}


def should_flag(field: FormField, role: FieldRole, verdict: Necessity, confidence: float) -> bool:
    if role is FieldRole.CREDENTIAL:
        # Telling someone their password is unnecessary is the one mistake that destroys
        # trust in everything else the product says.
        return False
    if verdict is Necessity.RED_FLAG:
        return True
    if role in _NEVER_FLAG or verdict in {Necessity.REQUIRED, Necessity.REASONABLE}:
        return False
    if confidence < MIN_INTENT_CONFIDENCE:
        return False
    # An optional box left empty costs nothing. Say something once it is compulsory, or
    # once the person has actually put something in it.
    engaged = field.required or field.asserted_required or field.filled
    return engaged and _worth_naming(field.category) if field.category else False


def assess_form(
    fields: list[FormField],
    context: FormContext | None = None,
    site_purpose: str = "unknown",
) -> FormJudgement:
    """Judge each field against what this form is actually for."""
    intent = classify_form(fields, context, site_purpose)
    confident = intent.confidence >= MIN_INTENT_CONFIDENCE
    effective = intent.intent if confident else FormIntent.UNKNOWN
    if effective is FormIntent.IDENTITY_VERIFICATION and not _verifies_identity(site_purpose):
        # "Verify your identity" is a claim, not a credential. An image compressor that
        # asks for a passport has not become a bank by saying so, and letting the request
        # justify itself is how a demand for ID talks its way past the check.
        effective = FormIntent.UNKNOWN
    judged: list[FieldJudgement] = []
    for field in fields:
        if field.category is None:
            judged.append(
                FieldJudgement(
                    field=field,
                    role=FieldRole.PROFILE_DETAIL,
                    verdict=Necessity.REASONABLE,
                    confidence=intent.confidence,
                )
            )
            continue
        verdict = verdict_for(
            field.category,
            effective,
            site_purpose=site_purpose,
            intent_confidence=intent.confidence,
            expected_credential=credential_expected(field, effective, intent.structure),
        )
        role = infer_role(field, effective, intent.structure, verdict)
        if role in {FieldRole.PRIMARY_IDENTIFIER, FieldRole.ALTERNATE_IDENTIFIER}:
            verdict = Necessity.REQUIRED
        judged.append(
            FieldJudgement(
                field=field,
                role=role,
                verdict=verdict,
                confidence=intent.confidence,
                rationale=explain_field(field.category, effective, verdict, role),
                flag=should_flag(field, role, verdict, intent.confidence),
            )
        )
    return FormJudgement(intent=intent, fields=judged, site_purpose=site_purpose)


def assessments_for(judgement: FormJudgement) -> list[NecessityAssessment]:
    """Bridge to the shape the risk scorer and explanation layer already consume."""
    seen: dict[DataCategory, NecessityAssessment] = {}
    order = [Necessity.REQUIRED, Necessity.REASONABLE, Necessity.UNNECESSARY, Necessity.RED_FLAG]
    for item in judgement.fields:
        category = item.field.category
        if category is None:
            continue
        existing = seen.get(category)
        if existing is not None and order.index(Necessity(existing.verdict)) >= order.index(
            item.verdict
        ):
            continue
        seen[category] = NecessityAssessment(
            category=category,
            verdict=item.verdict,
            confidence=item.confidence,
            rationale=item.rationale,
        )
    return list(seen.values())
