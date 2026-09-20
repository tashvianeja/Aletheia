from __future__ import annotations

from aletheia.core.events import Outcome, RedactedDocumentEvent, Requester
from aletheia.engine.context import SiteOrAppProfile
from aletheia.engine.decision import decide
from aletheia.engine.notice import notice_signature
from aletheia.engine.outcome import report_for
from aletheia.engine.preferences import LearnedRules, UserPreferences


def _event(path: str = "/tmp/redacted-document.pdf") -> RedactedDocumentEvent:
    return RedactedDocumentEvent(
        requester=Requester(
            kind="application", bundle_id="com.apple.preview", display_name="Preview"
        ),
        path=path,
        filename="redacted-document.pdf",
        marks=3,
    )


def test_an_opened_redacted_file_is_offered_its_original_back() -> None:
    decision = decide(_event(), [], SiteOrAppProfile(), UserPreferences(), LearnedRules())
    assert decision.outcome == Outcome.INFORM
    assert decision.primary_action == "unredact"
    assert "unredact" in decision.actions and "continue" in decision.actions
    assert decision.action_labels["unredact"] == "Restore original"
    assert "3 redaction boxes" in decision.headline
    assert "covered, not removed" in decision.body


def test_the_same_file_raises_one_card_and_another_file_its_own() -> None:
    assert notice_signature(_event()) == notice_signature(_event())
    assert notice_signature(_event()) != notice_signature(_event("/tmp/other.pdf"))


def test_restoring_ends_on_a_receipt_naming_the_new_file() -> None:
    event = _event()
    decision = decide(event, [], SiteOrAppProfile(), UserPreferences(), LearnedRules())
    report = report_for(
        event,
        decision,
        "unredact",
        {"filename": "redacted-document-restored.pdf", "folder": "/tmp"},
    )
    assert report is not None
    assert "redacted-document-restored.pdf" in report["headline"]
    assert "/tmp" in report["body"]
