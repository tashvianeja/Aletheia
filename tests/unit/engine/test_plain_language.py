"""Nothing reaches a card as a database key or as a sentence lifted off the page.

A check that answers "what does this mean for me" with `arbitration_or_class_waiver`,
and then quotes the paragraph it found it in, has handed the reader back the document
they opened the check to avoid reading.
"""

from __future__ import annotations

import re

from aletheia.analysis.forms import label_field
from aletheia.core.events import FormContext, FormField, FormObservedEvent, Requester
from aletheia.engine.clauses import CLAUSES
from aletheia.engine.decision import decide
from aletheia.engine.explain import UNCERTAIN_PURPOSE
from aletheia.engine.presentation import policy_rows

CLAUSE_LIST = [
    {
        "category": "arbitration_or_class_waiver",
        "citation": (
            "Any dispute arising out of or relating to these Terms shall be resolved by "
            "binding individual arbitration administered under the applicable rules, and "
            "you waive any right to a trial by jury or to participate in a class action."
        ),
    },
    {
        "category": "retention_after_deletion",
        "citation": "We may retain certain information after account closure.",
    },
    {"category": "liability_cap", "citation": "Our liability shall not exceed the fees paid."},
]


def test_a_row_says_what_the_clause_does_to_the_reader() -> None:
    rows = policy_rows(CLAUSE_LIST, [])
    assert [row.label for row in rows] == [
        "You give up the right to sue or to join a class action",
        "Deleting your account does not delete your data",
        "What you can claim back is capped",
    ]
    assert all(row.detail and not row.detail.startswith("Any dispute") for row in rows)


def test_the_document_s_own_sentence_travels_as_evidence_not_as_the_explanation() -> None:
    rows = policy_rows(CLAUSE_LIST, [])
    arbitration = rows[0]
    # Still there for "Show me where", still verbatim, but never the claim itself.
    assert arbitration.quote.startswith("Any dispute arising")
    assert arbitration.quote not in arbitration.label
    assert arbitration.quote not in arbitration.detail


def test_ordinary_contract_machinery_is_a_note_beside_a_warning() -> None:
    rows = policy_rows(CLAUSE_LIST, [])
    assert [row.severity for row in rows] == ["warn", "warn", "info"]


def test_the_things_that_turned_out_fine_are_said_in_words_too() -> None:
    rows = policy_rows([], ["payment", "account_creation", "basic_service_usage"])
    assert [row.label for row in rows] == [
        "Paying for it works the usual way",
        "Creating an account works the usual way",
        "Using the service works the usual way",
    ]
    assert {row.severity for row in rows} == {"ok"}


def test_no_wording_anywhere_is_a_machine_name_or_a_wall_of_legalese() -> None:
    for category, words in CLAUSES.items():
        assert "_" not in words.title, category
        assert "_" not in words.meaning, category
        # Sentences a person reads standing at a checkout, not clauses they scroll past.
        assert len(words.meaning.split()) <= 30, category
        assert not re.search(
            r"\b(?:herein|thereof|hereunder|pursuant|notwithstanding)\b",
            words.title + " " + words.meaning,
            re.I,
        ), category


def _survey_event() -> FormObservedEvent:
    """A form builder's survey: the site's industry says nothing, the form says plenty."""

    def ask(label: str) -> FormField:
        return label_field(
            FormField(field_id=label, label=label, name="entry.1", required=True, filled=True)
        )

    event = FormObservedEvent(
        requester=Requester(
            kind="website", origin="https://docs.example", display_name="docs.example"
        ),
        fields=[
            ask("Your name"),
            ask("Email address"),
            ask("What is your password?"),
            ask("Credit card number"),
        ],
        context=FormContext(
            heading="Customer feedback survey",
            submit_text="Submit",
            page_title="Untitled form",
            nearby_text="Tell us what you think of our service.",
        ),
    )
    event.data_categories = sorted(
        {field.category for field in event.fields if field.category}, key=str
    )
    return event


def test_a_card_does_not_name_the_task_and_then_deny_knowing_it() -> None:
    """The headline said "to answer a survey"; the line under it said the purpose was unknown.

    Two different things are called purpose: the site's line of business and what this
    form is for. Necessity is judged on the second, so the caveat about the first
    contradicted the sentence directly above it.
    """
    decision = decide(_survey_event())
    assert decision.headline == "This form is asking for more than it needs to answer a survey."
    assert UNCERTAIN_PURPOSE not in decision.body


def test_the_card_warns_about_exactly_what_it_would_badge() -> None:
    """A full name on a survey is not news, and a triangle beside it says it is.

    The card took every category the engine could not justify; the in-page badges took
    the ones worth raising. They now take the same set, so the two cannot disagree.
    """
    decision = decide(_survey_event())
    assert [(row.label, row.severity) for row in decision.findings] == [
        ("Password", "warn"),
        ("Card number", "warn"),
    ]


def test_a_field_that_is_merely_unexplained_is_never_ticked_as_needed() -> None:
    """With nothing to warn about, the remaining rows must not claim more than they know.

    A name on a survey is neither needed nor worth interrupting anyone about, and both
    a tick saying "needed for this" and a triangle saying otherwise are claims the
    engine cannot support.
    """
    event = _survey_event()
    event.fields = event.fields[:2]
    event.data_categories = sorted(
        {field.category for field in event.fields if field.category}, key=str
    )
    decision = decide(event)
    assert [(row.label, row.severity) for row in decision.findings] == [
        ("Full name", "info"),
        ("Email — needed for this", "ok"),
    ]
    # Nothing was raised, so the card does not announce over-collection either.
    assert decision.headline == "docs.example is asking for your details."


def test_the_reasoning_panel_answers_in_the_form_s_own_terms() -> None:
    reasoning = " ".join(decide(_survey_event()).rationale)
    assert "nothing to sign in to here" in reasoning
    assert "not needed to answer a survey" in reasoning
