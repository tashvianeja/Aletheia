"""What each workflow says for itself once it has run."""

from __future__ import annotations

from aletheia.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    FileUploadEvent,
    FormContext,
    FormField,
    FormObservedEvent,
    FormSubmitEvent,
    Outcome,
    PermissionRequestEvent,
    Requester,
    TrackingEvent,
)
from aletheia.engine.decision import (
    clearable_fields,
    decide,
    form_assessments,
    redactable_fields,
)
from aletheia.engine.outcome import report_for


def site(origin: str, purpose: str) -> Requester:
    return Requester(
        origin=origin, display_name=origin.split("//")[-1], purpose=purpose, purpose_confidence=0.9
    )


def free_download() -> FormSubmitEvent:
    return FormSubmitEvent(
        requester=site("https://templatehive.example", "free_download"),
        fields=[
            FormField(field_id="name", category=DataCategory.FULL_NAME, filled=True, required=True),
            FormField(field_id="email", category=DataCategory.EMAIL, filled=True, required=True),
            FormField(field_id="phone", category=DataCategory.PHONE, filled=True),
            FormField(field_id="dob", category=DataCategory.DOB, filled=True),
            FormField(field_id="addr", category=DataCategory.POSTAL_ADDRESS, filled=True),
        ],
        context=FormContext(submit_text="Get the guide", heading="Download a free PDF guide"),
    )


def test_a_redacted_copy_names_what_it_took_out_and_where_it_stayed() -> None:
    upload = FileUploadEvent(
        filename="passport.pdf",
        requester=site("https://shrinkpix.example", "image_tool"),
        data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT, DataCategory.DOB],
    )
    report = report_for(upload, decide(upload), "redact", {"filename": "redacted-document.pdf"})
    assert report is not None
    assert report["headline"] == "Redacted copy ready: redacted-document.pdf"
    assert (
        report["body"]
        == "Passport number and date of birth covered with black boxes. Nothing left this device."
    )
    assert (report["subject"], report["destination"]) == ("passport.pdf", "shrinkpix.example")


def test_sending_only_what_is_needed_names_the_fields_left_blank() -> None:
    form = free_download()
    decision = decide(form)
    assert "clear_fields" in decision.actions and decision.primary_action == "clear_fields"
    assert decision.action_labels["clear_fields"] == "Send only what's needed"

    cleared = ["phone", "dob", "addr"]
    report = report_for(form, decision, "clear_fields", {"fields": cleared})
    assert report is not None
    assert report["headline"] == "3 fields left blank before sending"
    assert report["body"] == (
        "Phone number, date of birth and home address stayed with you. The rest was sent as normal."
    )
    one = report_for(form, decision, "clear_fields", {"fields": ["phone"]})
    assert one is not None and one["headline"] == "1 field left blank before sending"


def test_only_filled_optional_fields_the_card_warned_about_are_blanked() -> None:
    form = free_download()
    flagged = {DataCategory.PHONE, DataCategory.DOB, DataCategory.POSTAL_ADDRESS}
    assert clearable_fields(form, flagged) == ["phone", "dob", "addr"]

    insisting = form.model_copy(
        update={
            "fields": [
                field.model_copy(update={"required": True}) if field.field_id == "phone" else field
                for field in form.fields
            ]
        }
    )
    assert clearable_fields(insisting, flagged) == ["dob", "addr"], (
        "a field the form insists on cannot be sent empty"
    )
    all_required = form.model_copy(
        update={"fields": [field.model_copy(update={"required": True}) for field in form.fields]}
    )
    assert "clear_fields" not in decide(all_required).actions, (
        "a button that could blank nothing is not offered"
    )


def test_blocking_counts_the_companies_it_shut_out() -> None:
    page = TrackingEvent(
        requester=site("https://shop.example", "ecommerce"),
        data_categories=[DataCategory.DEVICE_IDENTIFIERS],
        tracker_domains=["a.test", "b.test", "a.test"],
        confidence=0.8,
        signals=["tracking_pixels"],
    )
    report = report_for(page, decide(page), "block", {})
    assert report is not None
    assert report["headline"] == "Tracking limited on shop.example"
    assert report["body"].startswith("Requests to 2 tracking companies are now blocked")
    lone = page.model_copy(update={"tracker_domains": ["a.test"]})
    lone_report = report_for(lone, decide(lone), "block", {})
    assert lone_report is not None and "1 tracking company are" in lone_report["body"]


def test_rejecting_cookies_says_what_was_kept_and_how_to_say_it_failed() -> None:
    banner = ConsentBannerEvent(
        requester=site("https://news.example", "news"),
        purposes=["necessary", "analytics", "advertising"],
        dark_patterns=["buried_reject"],
    )
    report = report_for(banner, decide(banner), "reject_optional", {})
    assert report is not None
    assert report["headline"] == "Optional cookies rejected on news.example"
    assert report["body"] == "Necessary cookies were kept."
    assert "could not be found" in report["failed"]["headline"]
    remembered = report_for(banner, decide(banner), "reject_optional", {"remembered": True})
    assert remembered is not None and remembered["body"].endswith("Remembered for next time.")


def test_desktop_workflows_say_what_they_did_in_the_app_s_name() -> None:
    read = ClipboardReadEvent(
        requester=Requester(
            kind="application", bundle_id="com.snippetly", display_name="Snippetly"
        ),
        data_categories=[DataCategory.CREDENTIALS_PASSWORD],
        writer_key="other",
    )
    cleared = report_for(read, decide(read), "clear_clipboard", {})
    assert cleared is not None and cleared["headline"] == "Clipboard cleared"
    assert cleared["body"] == (
        "What looked like a password is no longer on it, so Snippetly cannot read it again."
    )

    camera = PermissionRequestEvent(
        source="os",
        requester=Requester(kind="application", bundle_id="com.swiftpdf", display_name="SwiftPDF"),
        data_categories=[DataCategory.CAMERA],
        permission="camera",
    )
    opened = report_for(camera, decide(camera), "open_settings", {})
    assert opened is not None and opened["body"] == "Camera for SwiftPDF can be turned off there."
    expected = report_for(camera, decide(camera), "mark_expected", {})
    assert expected is not None and expected["headline"] == "Marked as expected for SwiftPDF"


def test_answers_that_do_nothing_have_nothing_to_report() -> None:
    upload = FileUploadEvent(
        filename="passport.pdf",
        requester=site("https://shrinkpix.example", "image_tool"),
        data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT],
    )
    decision = decide(upload)
    assert report_for(upload, decision, "continue", {}) is None
    assert report_for(upload, decision, "cancel", {}) is None


def survey() -> FormObservedEvent:
    """A feedback survey asking for a password and a card number, both typed in.

    The form has no login and nothing to charge, so neither box is the credential or
    the payment instrument of anything: they are a survey collecting two things it has
    no business collecting.
    """
    return FormObservedEvent(
        requester=site("https://feedback.example", "survey"),
        fields=[
            FormField(field_id="f1", label="Your name", filled=True),
            FormField(field_id="f2", label="Email address", filled=True),
            FormField(field_id="f3", label="What is your password?", filled=True),
            FormField(field_id="f4", label="Credit card number", filled=True),
        ],
        context=FormContext(
            submit_text="Submit",
            heading="Customer feedback survey",
            page_title="Untitled form",
            nearby_text="Customer feedback survey. Tell us what you think of our service.",
        ),
    )


def labelled(event: FormObservedEvent) -> FormObservedEvent:
    """The event as the service hands it to the engine, with its fields categorised."""
    from aletheia.analysis.forms import label_field

    fields = [label_field(field) for field in event.fields]
    return event.model_copy(
        update={
            "fields": fields,
            "data_categories": sorted(
                {field.category for field in fields if field.category is not None}, key=str
            ),
        }
    )


def test_a_form_asking_for_a_password_and_a_card_offers_one_card_for_both() -> None:
    """The user's report: a badge appeared beside each box and said nothing could be
    done. One card now covers the whole form, names every field it is warning about,
    and offers the workflow that deals with all of them at once."""
    form = labelled(survey())
    decision = decide(form)

    # A form sitting on a page holds nothing up, so this card asks for no decision.
    assert decision.outcome is Outcome.INFORM
    assert decision.headline == "This form is asking for more than it needs to answer a survey."
    assert [finding.label for finding in decision.findings] == ["Password", "Card number"]
    assert "redact_fields" in decision.actions and decision.primary_action == "redact_fields"
    assert decision.action_labels["redact_fields"] == "Redact these fields"

    _assessments, flagged = form_assessments(form)
    assert redactable_fields(form, flagged) == ["f3", "f4"], "one workflow, both fields"


def test_redacting_a_form_names_the_boxes_that_now_hold_bullets() -> None:
    form = labelled(survey())
    decision = decide(form)
    report = report_for(form, decision, "redact_fields", {"fields": ["f3", "f4"]})
    assert report is not None
    assert report["headline"] == "2 fields replaced with bullets"
    assert report["body"] == (
        "Password and card number stayed with you. Those boxes now read as bullets, "
        "so feedback.example never sees what you typed."
    )
    assert (report["subject"], report["destination"]) == ("Form on this page", "feedback.example")
    one = report_for(form, decision, "redact_fields", {"fields": ["f3"]})
    assert one is not None and one["headline"] == "1 field replaced with bullets"


def test_only_boxes_with_something_typed_in_them_are_redacted() -> None:
    """Redaction replaces contents, so a box still empty has nothing to hide, and a
    card offering to redact nothing is a button that does nothing."""
    form = labelled(survey())
    _assessments, flagged = form_assessments(form)

    untouched = form.model_copy(
        update={
            "fields": [
                field.model_copy(update={"filled": False}) if field.field_id == "f3" else field
                for field in form.fields
            ]
        }
    )
    assert redactable_fields(untouched, flagged) == ["f4"]

    empty = form.model_copy(
        update={"fields": [field.model_copy(update={"filled": False}) for field in form.fields]}
    )
    assert redactable_fields(empty, flagged) == []
    assert "redact_fields" not in decide(empty).actions


def test_a_box_that_could_not_hold_bullets_is_left_to_be_blanked_instead() -> None:
    """A tick, a dropdown or a date picker keeps only the shapes of value it knows, so
    bullets written into one are discarded or empty it."""
    form = labelled(survey())
    _assessments, flagged = form_assessments(form)
    picker = form.model_copy(
        update={
            "fields": [
                field.model_copy(update={"input_type": "date"}) if field.field_id == "f4" else field
                for field in form.fields
            ]
        }
    )
    assert redactable_fields(picker, flagged) == ["f3"]


def test_a_field_the_form_insists_on_can_still_be_redacted() -> None:
    """The point of bullets over blanking: the box stays filled, so the form still
    validates, and the site still never sees the real answer."""
    form = labelled(survey())
    _assessments, flagged = form_assessments(form)
    compulsory = form.model_copy(
        update={"fields": [field.model_copy(update={"required": True}) for field in form.fields]}
    )
    assert clearable_fields(compulsory, flagged) == [], "blanking cannot touch a required box"
    assert redactable_fields(compulsory, flagged) == ["f3", "f4"]
    assert "redact_fields" in decide(compulsory).actions
