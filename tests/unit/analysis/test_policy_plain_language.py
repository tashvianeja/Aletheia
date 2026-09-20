"""What a document says, said in the reader's words and only where it says it.

Three failures sat behind these cases, all of them the same mistake in different places.
A check that reads a contract and hands back the contract has done nothing for the person
reading it. A pattern that fires on a number near the words "at least" names a
cancellation notice an age requirement. And a category list matched against any sentence
mentioning "information" reports collection the document never claims.
"""

from __future__ import annotations

import pytest

from aletheia.analysis.policy import analyze_policy, analyze_terms
from aletheia.analysis.policy.analyzer import patterns
from aletheia.engine.clauses import CLAUSES, clause_title, is_material

# The clause that started this: a subscription's notice period, reported as an age limit
# because "at least 14" looks like "at least 18" to a pattern that never asked what the
# number counted.
CANCELLATION = (
    "Subscriptions\n"
    "Your subscription renews automatically. To cancel you must notify us at least "
    "14 days before the renewal date, otherwise you will be charged for the next period.\n"
)
AGE_LIMIT = "Eligibility\nYou must be at least 18 years old to use the Service.\n"


def categories(text: str) -> set[str]:
    return {clause.category for clause in analyze_terms(text).clauses}


def test_a_cancellation_notice_period_is_not_an_age_requirement() -> None:
    assert "minimum_age" not in categories(CANCELLATION)
    assert "automatic_renewal" in categories(CANCELLATION)


def test_a_real_age_limit_is_still_reported_and_quoted_from_its_own_sentence() -> None:
    profile = analyze_terms(CANCELLATION + AGE_LIMIT)
    age = next(clause for clause in profile.clauses if clause.category == "minimum_age")
    assert "18 years old" in age.citation
    assert "renewal date" not in age.citation


@pytest.mark.parametrize(
    ("category", "text"),
    [
        # A licence granted to the user is the opposite of one taken from them.
        (
            "content_licence_to_provider",
            "We grant you a worldwide, royalty-free licence to use the software.",
        ),
        # Every company is sold eventually; that is not a sale of your data.
        ("data_sale", "In the event of a sale of the business, this agreement transfers."),
        # A limited liability company is a kind of company, not a cap on damages.
        ("liability_cap", "Synthetic Tools Limited Liability Company operates this site."),
        # Training staff is not training a model on your files.
        ("training_on_user_content", "We train our staff to handle your data carefully."),
        # Scheduled downtime is not your account being closed on a whim.
        (
            "account_termination_without_notice",
            "We may suspend the service without notice for scheduled maintenance.",
        ),
    ],
)
def test_a_clause_is_not_claimed_by_a_sentence_about_something_else(
    category: str, text: str
) -> None:
    assert category not in categories(text)


def test_prose_that_mentions_a_category_without_collecting_it_claims_nothing() -> None:
    """The words appear; the collection does not. Saying otherwise is inventing a claim."""
    profile = analyze_policy(
        "We use your information to provide the service and for educational purposes. "
        "We do not discriminate on the basis of sex, gender identity, race or religion. "
        "In the course of employment, our staff may access data to support you. "
        "We may store the name of the file you upload for diagnostic purposes.",
        purpose="file_converter",
    )
    assert {category.value for category in profile.collects} == set()
    assert profile.necessity_statements == []


def test_a_real_collection_statement_is_still_read() -> None:
    profile = analyze_policy(
        "We collect the email address you provide when you create an account. "
        "We also collect technical information such as your IP address and browser type.",
        purpose="file_converter",
    )
    assert {category.value for category in profile.collects} == {"email", "device_identifiers"}


def test_what_they_do_with_data_is_not_a_claim_that_they_took_it() -> None:
    profile = analyze_policy("We use browsing activity for personalised advertising.")
    assert "browsing_activity" not in {category.value for category in profile.collects}
    assert "personalised_ads" in profile.purposes


def test_every_clause_the_detector_can_find_has_words_a_person_would_use() -> None:
    """A new pattern must not reach a card as its own database key."""
    missing = sorted(set(patterns()) - set(CLAUSES))
    assert missing == [], f"no plain wording for {missing}"
    for category in CLAUSES:
        title = clause_title(category)
        assert "_" not in title
        assert title == title.strip()
        # Titles say what happens to the reader, so they read as sentences about them.
        assert len(title.split()) >= 4


def test_routine_contract_machinery_is_a_note_rather_than_a_warning() -> None:
    assert not is_material("liability_cap")
    assert not is_material("governing_law_foreign")
    assert not is_material("minimum_age")
    assert is_material("data_sale")
    assert is_material("retention_after_deletion")


# A whole document at once: the wording a real policy and a real set of terms use, with
# every trap that produced a wrong claim sitting in its natural place rather than alone
# in a one-line case.
REAL_POLICY = """
Privacy Policy

Information We Collect
We collect information you provide directly to us, such as your name, email address and phone number when you create an account.
We automatically collect certain information about your device, including your IP address, browser type and operating system.

How We Use Information
We use the information we collect to provide, maintain and improve our services, and to comply with our legal obligations.
We are committed to equal treatment regardless of race, sex, gender identity or religion.
Our services are not intended for educational institutions.

Sharing
We share information with service providers who perform services on our behalf.
We do not sell your personal information.

Children
Our services are not directed to children under the age of 13.
"""

REAL_TERMS = """
Terms of Service

Eligibility
You must be at least 13 years old to create an account.

Subscriptions and Billing
Paid plans renew automatically at the end of each billing period. You may cancel at any time, but you must cancel at least 3 days before the renewal date to avoid being charged.

Your Content
You grant us a worldwide, non-exclusive, royalty-free licence to host, reproduce and display your content in order to operate the service.

Our Software
We grant you a limited, revocable licence to use the application.

Disputes
These Terms are governed by the laws of the State of Delaware. Any dispute shall be resolved by binding individual arbitration.
"""


def test_a_whole_policy_claims_what_it_says_and_nothing_else() -> None:
    profile = analyze_policy(REAL_POLICY, purpose="file_converter")
    assert {category.value for category in profile.collects} == {
        "full_name",
        "email",
        "phone",
        "device_identifiers",
    }
    assert profile.shares_with == ["service_providers"]
    # It says in plain words that it does not sell, so nothing may report that it does.
    assert "data_sale" not in {clause.category for clause in profile.clauses}


def test_a_whole_set_of_terms_names_each_clause_from_its_own_sentence() -> None:
    profile = analyze_terms(REAL_TERMS)
    quoted = {clause.category: clause.citation for clause in profile.clauses}
    assert quoted.keys() == {
        "minimum_age",
        "automatic_renewal",
        "content_licence_to_provider",
        "governing_law_foreign",
        "arbitration_or_class_waiver",
    }
    assert "13 years old" in quoted["minimum_age"]
    # The licence the service takes, not the one it hands back with the software.
    assert "host, reproduce and display your content" in quoted["content_licence_to_provider"]
    assert "limited, revocable" not in quoted["content_licence_to_provider"]
