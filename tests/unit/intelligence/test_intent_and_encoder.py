"""The on-device encoder, and what happens when it is not there."""

from __future__ import annotations

import time

import pytest

from aletheia.analysis.forms import label_field
from aletheia.core.events import FormContext, FormField
from aletheia.intelligence import embedder
from aletheia.intelligence.intent import classify_form, describe
from aletheia.intelligence.necessity import assess_form
from aletheia.intelligence.taxonomy import FormIntent
from aletheia.intelligence.tokenizer import encode, vocabulary


def field(label: str, name: str = "", **kwargs: object) -> FormField:
    return label_field(FormField(field_id=name or label, label=label, name=name, **kwargs))  # type: ignore[arg-type]


def test_wordpiece_matches_the_reference_bert_encoding() -> None:
    vocab = vocabulary()
    ids, mask = encode("Mobile Number or Email")
    assert ids[0] == vocab["[CLS]"] and ids[-1] == vocab["[SEP]"]
    assert [ids[1], ids[2], ids[3], ids[4]] == [
        vocab["mobile"],
        vocab["number"],
        vocab["or"],
        vocab["email"],
    ]
    assert mask == [1] * len(ids)


def test_accented_and_unaccented_labels_tokenize_alike() -> None:
    assert encode("Teléfono")[0] == encode("Telefono")[0]


def test_encoder_produces_normalised_vectors_when_the_weights_are_present() -> None:
    vectors = embedder.embed(["Create your account", "Log in"])
    if vectors is None:
        pytest.skip("sentence encoder weights are not installed")
    assert vectors.shape == (2, embedder.DIMENSIONS)
    assert all(abs(float((row * row).sum()) - 1.0) < 1e-4 for row in vectors)


def test_the_weights_are_handed_back_once_nobody_is_filling_in_forms() -> None:
    """A 95 MB resident model must not sit in an idle process holding a 200 MB budget."""
    if not embedder.available():
        pytest.skip("sentence encoder weights are not installed")
    assert embedder.release_if_idle() is False
    assert embedder.release_if_idle(time.monotonic() + embedder.IDLE_RELEASE_SECONDS + 1) is True
    assert embedder.available() is True  # reloads on demand


@pytest.mark.parametrize(
    ("intent", "context", "fields"),
    [
        (
            FormIntent.ACCOUNT_LOGIN,
            FormContext(heading="Sign in", submit_text="Log in"),
            [
                field("Email", "e", input_type="email"),
                field("Password", "p", input_type="password", autocomplete="current-password"),
            ],
        ),
        (
            FormIntent.CHECKOUT_PAYMENT,
            FormContext(heading="Payment", submit_text="Pay now"),
            [field("Card number", "cc", autocomplete="cc-number")],
        ),
        (
            FormIntent.TWO_FACTOR,
            FormContext(heading="Verification", submit_text="Verify"),
            [field("Code", "otp", autocomplete="one-time-code", max_length=6)],
        ),
        (
            FormIntent.SEARCH_FILTER,
            FormContext(submit_text="Search"),
            [field("Search", "q", input_type="search")],
        ),
    ],
)
def test_form_shape_alone_identifies_the_common_transactions(
    intent: FormIntent, context: FormContext, fields: list[FormField]
) -> None:
    assert classify_form(fields, context).intent is intent


def test_a_short_numeric_code_box_is_not_read_as_a_phone_number() -> None:
    structure = describe([field("Verification code", "code", input_type="tel", max_length=6)])
    assert structure.one_time_code is True


def test_judgement_still_runs_and_stays_quiet_without_the_encoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing weights must cost recall, never precision: silence, not false alarms."""
    monkeypatch.setattr(embedder, "_UNAVAILABLE", True)
    monkeypatch.setattr(embedder, "_SESSION", None)
    fields = [
        field("Mobile Number or Email", "emailOrPhone", required=True),
        field(
            "Password",
            "password",
            input_type="password",
            autocomplete="new-password",
            required=True,
        ),
    ]
    judgement = assess_form(fields, FormContext(submit_text="Sign up"), "social")
    assert judgement.intent.semantic is False
    assert not judgement.flagged
