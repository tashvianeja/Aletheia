"""What each workflow says for itself once it has run."""

from __future__ import annotations

from privacy_guardian.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    FileUploadEvent,
    FormContext,
    FormField,
    FormSubmitEvent,
    PermissionRequestEvent,
    Requester,
    TrackingEvent,
)
from privacy_guardian.engine.decision import clearable_fields, decide
from privacy_guardian.engine.outcome import report_for


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
