"""What each clause in a policy or a set of terms means, in the reader's words.

The detector's names for clauses are database keys: `arbitration_or_class_waiver`,
`content_licence_to_provider`, `retention_after_deletion`. Putting those on a card, or
pasting the sentence they matched straight off the page, hands the reader the same
legalese they opened the check to avoid. Every surface that shows a clause — the card,
the thorough check, the reasoning panel — takes its words from here, so the quoted
sentence is only ever the receipt for a claim already made in plain English.
"""

from __future__ import annotations

from typing import NamedTuple


class Wording(NamedTuple):
    title: str
    meaning: str
    material: bool


# title: what it does to you, as a sentence someone can act on.
# meaning: the one line of "so what", for the reasoning panel and the detail row.
# material: whether it changes the decision, or is the ordinary boilerplate every
# contract carries. Reporting a liability cap as a warning next to "your data can be
# sold" says the two are comparable, and they are not.
CLAUSES: dict[str, Wording] = {
    "third_party_sharing": Wording(
        "Your information is passed on to other companies",
        "Partners, advertisers or contractors can receive what this service knows about you.",
        True,
    ),
    "data_sale": Wording(
        "Your information can be sold",
        "The policy keeps the right to sell what it holds about you to other companies.",
        True,
    ),
    "content_licence_to_provider": Wording(
        "They keep a licence to use whatever you upload",
        "Anything you post can be copied, changed and re-published by them, "
        "worldwide and without paying you.",
        True,
    ),
    "training_on_user_content": Wording(
        "What you upload can be used to train their AI",
        "Files, text or images you send can be fed into machine-learning models.",
        True,
    ),
    "retention_after_deletion": Wording(
        "Deleting your account does not delete your data",
        "Copies can be kept after you close the account or delete the file.",
        True,
    ),
    "arbitration_or_class_waiver": Wording(
        "You give up the right to sue or to join a class action",
        "Disputes go to a private arbitrator under their rules instead of to a court.",
        True,
    ),
    "unilateral_change_of_terms": Wording(
        "They can change these terms whenever they like",
        "What you agree to today can be rewritten later, sometimes without telling you.",
        True,
    ),
    "automatic_renewal": Wording(
        "This renews and charges you automatically",
        "Billing continues until you cancel, and cancelling may have to be done in advance.",
        True,
    ),
    "account_termination_without_notice": Wording(
        "Your account can be closed without warning",
        "They can suspend or delete it at their own discretion, "
        "and you may lose what is stored in it.",
        True,
    ),
    "cross_border_transfer": Wording(
        "Your data can be moved to other countries",
        "It may be stored or handled somewhere with weaker privacy laws than yours.",
        True,
    ),
    "governing_law_foreign": Wording(
        "Any dispute is settled under the law they choose",
        "A complaint has to be brought under the law and in the courts named in the terms, "
        "which may not be where you live.",
        False,
    ),
    "liability_cap": Wording(
        "What you can claim back is capped",
        "If something goes wrong, the terms limit the most they will pay.",
        False,
    ),
    "minimum_age": Wording(
        "There is a minimum age for using this",
        "The terms set an age you have to have reached before you may sign up.",
        False,
    ),
}

# The routine parts of an agreement, named the way a person would say them.
ORDINARY = {
    "payment": "Paying for it works the usual way",
    "account_creation": "Creating an account works the usual way",
    "basic_service_usage": "Using the service works the usual way",
}


def _fallback(category: str) -> Wording:
    spoken = category.replace("_", " ")
    return Wording(spoken[:1].upper() + spoken[1:], "", True)


def wording(category: str) -> Wording:
    return CLAUSES.get(category, _fallback(category))


def clause_title(category: str) -> str:
    return wording(category).title


def clause_meaning(category: str) -> str:
    return wording(category).meaning


def is_material(category: str) -> bool:
    """Whether this clause is worth a warning rather than a note."""
    return wording(category).material


def ordinary_label(item: str) -> str:
    spoken = item.replace("_", " ")
    return ORDINARY.get(item, spoken[:1].upper() + spoken[1:])
