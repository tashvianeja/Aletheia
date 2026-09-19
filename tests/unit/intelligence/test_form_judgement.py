"""What a form is for decides whether its fields are necessary.

Judging necessity from the site's industry alone reported Instagram's account identifier
and password as unnecessary, because a "social network" table has no way to tell a
registration form from a mailing-list box. These cases pin both directions: the ordinary
things people do every day stay silent, and real over-collection is still named.
"""

from __future__ import annotations

import pytest

from privacy_guardian.analysis.forms import label_field
from privacy_guardian.core.events import DataCategory, FormContext, FormField
from privacy_guardian.intelligence import embedder
from privacy_guardian.intelligence.necessity import assess_form
from privacy_guardian.intelligence.taxonomy import FieldRole, FormIntent

# Recognising over-collection needs the sentence encoder: structure alone cannot tell a
# mailing-list box from a registration form. Cases that must stay SILENT run either way,
# because losing the encoder must never cost precision.
needs_encoder = pytest.mark.skipif(
    not embedder.available(),
    reason="on-device sentence encoder not installed; run scripts/fetch_model.py",
)


def field(
    label: str,
    name: str = "",
    autocomplete: str = "",
    input_type: str = "text",
    required: bool = False,
    filled: bool = True,
    max_length: int = 0,
) -> FormField:
    return label_field(
        FormField(
            field_id=name or label,
            label=label,
            name=name,
            autocomplete=autocomplete,
            input_type=input_type,
            required=required,
            filled=filled,
            max_length=max_length,
        )
    )


def flagged(*args: object, **kwargs: object) -> set[str]:
    judgement = assess_form(*args, **kwargs)  # type: ignore[arg-type]
    return {item.field.category.value for item in judgement.flagged if item.field.category}


SIGNUP = FormContext(
    heading="Sign up to see photos and videos from your friends.",
    submit_text="Sign up",
    page_title="Instagram",
)
SIGNUP_FIELDS = [
    field("Mobile Number or Email", "emailOrPhone", required=True),
    field("Full Name", "fullName", required=True),
    field("Username", "username", required=True),
    field(
        "Password", "password", input_type="password", autocomplete="new-password", required=True
    ),
]


def test_account_identifier_on_a_signup_form_is_not_over_collection() -> None:
    judgement = assess_form(SIGNUP_FIELDS, SIGNUP, "social")
    assert judgement.intent.intent is FormIntent.ACCOUNT_SIGNUP
    assert not judgement.flagged
    identifier = judgement.fields[0]
    assert identifier.role is FieldRole.ALTERNATE_IDENTIFIER
    assert "identified" in identifier.rationale


@pytest.mark.parametrize(
    ("heading", "submit", "autocomplete"),
    [("Log in", "Log in", "current-password"), ("Sign up", "Sign up", "new-password")],
)
def test_a_password_is_never_reported_as_unnecessary(
    heading: str, submit: str, autocomplete: str
) -> None:
    fields = [
        field("Email", "email", input_type="email", required=True),
        field(
            "Password", "password", input_type="password", autocomplete=autocomplete, required=True
        ),
    ]
    judgement = assess_form(fields, FormContext(heading=heading, submit_text=submit), "social")
    password = judgement.fields[1]
    assert password.role is FieldRole.CREDENTIAL
    assert not password.flag


@needs_encoder
def test_a_mailing_list_does_not_need_a_phone_number_or_a_birthday() -> None:
    fields = [
        field("Email", "email", input_type="email", required=True),
        field("Mobile number", "tel", autocomplete="tel", required=True),
        field("Date of birth", "dob", autocomplete="bday", required=True),
    ]
    context = FormContext(heading="Never miss a recipe", submit_text="Subscribe")
    assert flagged(fields, context, "recipe") == {"phone", "dob"}


@needs_encoder
def test_a_phone_number_behind_a_free_download_is_named_as_a_sales_call() -> None:
    fields = [
        field("Work email", "email", input_type="email", required=True),
        field("Phone number", "tel", autocomplete="tel", required=True),
    ]
    context = FormContext(
        heading="Download our free 2026 salary guide", submit_text="Get the free guide"
    )
    judgement = assess_form(fields, context, "free_download")
    assert judgement.intent.intent is FormIntent.LEAD_CAPTURE
    assert [item.field.category for item in judgement.flagged] == [DataCategory.PHONE]
    assert "sales call" in judgement.flagged[0].rationale


def test_an_image_tool_asking_for_a_passport_is_still_a_red_flag() -> None:
    """A form claiming to verify identity cannot thereby justify collecting it."""
    fields = [field("Passport number", "passport", required=True)]
    context = FormContext(heading="Verify your identity", submit_text="Continue")
    judgement = assess_form(fields, context, "image_tool")
    assert judgement.flagged
    assert judgement.flagged[0].verdict == "red_flag"


def test_a_bank_verifying_identity_says_nothing() -> None:
    fields = [
        field("Social Security Number", "ssn", required=True),
        field("Date of birth", "dob", autocomplete="bday", required=True),
        field("Home address", "addr", autocomplete="street-address", required=True),
    ]
    context = FormContext(heading="Verify your identity", submit_text="Submit")
    assert flagged(fields, context, "banking") == set()


def test_payment_and_delivery_details_are_not_flagged_where_they_belong() -> None:
    checkout = [
        field("Card number", "cc", autocomplete="cc-number", required=True),
        field("Billing address", "addr", autocomplete="billing street-address", required=True),
        field("Phone number", "tel", autocomplete="tel", required=True),
    ]
    context = FormContext(heading="Payment method", submit_text="Place your order")
    assert flagged(checkout, context, "ecommerce") == set()


@needs_encoder
def test_bank_details_on_a_job_application_are_flagged_despite_looking_like_payment() -> None:
    fields = [
        field("Full name", "name", autocomplete="name", required=True),
        field("Bank account number", "bank", required=True),
    ]
    context = FormContext(heading="Apply for this job", submit_text="Submit application")
    assert flagged(fields, context, "job_board") == {"financial.account_number"}


def test_an_empty_optional_box_is_not_worth_interrupting_anyone_about() -> None:
    fields = [
        field("Email", "email", input_type="email", required=True),
        field("Password", "p", input_type="password", autocomplete="new-password", required=True),
        field("Phone (optional)", "tel", autocomplete="tel", filled=False),
    ]
    context = FormContext(heading="Sign up for free", submit_text="Sign up")
    assert flagged(fields, context, "music_streaming") == set()


def test_an_unrecognisable_form_says_nothing_rather_than_guessing() -> None:
    fields = [field("Reference", "ref", required=True), field("Code", "code", required=True)]
    assert flagged(fields, FormContext(), "unknown") == set()


# A form builder hands over its questions as written, with no autocomplete hint and no
# password control: "What is your password?" is a plain text box like any other.
SURVEY = FormContext(
    heading="Customer feedback survey",
    submit_text="Submit",
    page_title="Untitled form",
    nearby_text="Tell us what you think of our service.",
)


@needs_encoder
def test_a_survey_asking_for_a_password_is_the_thing_most_worth_saying() -> None:
    """Never calling a password unnecessary protected logins by silencing this.

    The rule was written for a sign-in page, where telling someone their password is
    over-collection destroys trust in everything else. Applied to every form, it also
    silenced the one request nobody should ever answer.
    """
    fields = [
        field("Your name", required=True),
        field("Email address", required=True),
        field("What is your password?", required=True),
    ]
    judgement = assess_form(fields, SURVEY, "unknown")
    password = judgement.fields[2]
    assert password.field.category is DataCategory.CREDENTIALS_PASSWORD
    assert password.role is FieldRole.UNRELATED_COLLECTION
    assert password.flag
    assert "nothing to sign in to here" in password.rationale


@needs_encoder
def test_a_survey_asking_for_a_card_number_is_flagged_without_a_payment_to_make() -> None:
    fields = [
        field("Email address", required=True),
        field("Credit card number", required=True),
    ]
    assert flagged(fields, SURVEY, "unknown") == {"financial.card_number"}


@needs_encoder
def test_an_anonymous_box_cannot_be_judged_at_all() -> None:
    """Why the questions have to reach here: with no wording there is nothing to judge."""
    anonymous = [field("", name="entry.1"), field("", name="entry.2")]
    assert flagged(anonymous, SURVEY, "unknown") == set()


def test_an_email_address_is_not_a_home_address() -> None:
    """`address` matched before `email` did, purely because it sat higher in the table."""
    assert field("Email address").category is DataCategory.EMAIL
    assert field("Home address").category is DataCategory.POSTAL_ADDRESS
    assert field("What was the name of your first pet?").category is None
