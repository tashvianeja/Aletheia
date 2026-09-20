from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QTextEdit

from privacy_guardian.core.events import (
    ConsentBannerEvent,
    DataCategory,
    Decision,
    FileUploadEvent,
    Outcome,
    PrivacyEvent,
    Requester,
    TrackingEvent,
    UserResponse,
)
from privacy_guardian.engine.preferences import LearnedRule, Preference
from privacy_guardian.llm.client import SUGGESTED_MODELS, ConnectionCheck
from privacy_guardian.ui.dashboard import Dashboard


def seed_history(controller) -> None:
    for event_id, origin, outcome in (
        ("one", "https://one.example/path?secret=yes", Outcome.INTERVENE),
        ("two", "https://two.example", Outcome.INFORM),
    ):
        event = PrivacyEvent(
            id=event_id,
            requester=Requester(origin=origin, display_name=origin),
            data_categories=[DataCategory.EMAIL],
        )
        controller.core.store.save_event(event)
        controller.core.store.save_decision(
            Decision(
                event_id=event.id,
                outcome=outcome,
                risk=0.7,
                explanation=f"Decision for {origin}",
                actions=["cancel"],
            )
        )


def test_history_filters_and_detail_view(qtbot, ui_controller) -> None:
    seed_history(ui_controller)
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.select("events")
    assert dashboard.history.rowCount() == 2

    dashboard.requester_filter.setText("https://one.example")
    assert dashboard.history.rowCount() == 1
    dashboard.outcome_filter.setCurrentText("INTERVENE")
    assert dashboard.history.rowCount() == 1
    dashboard.show_event_detail(0, 0)

    # The record is still gathered, but nothing sends the person to a pane that no
    # longer displays one.
    assert dashboard.current_section == "events"
    detail = json.loads(dashboard.profile_detail.toPlainText())
    assert detail["decision"]["outcome"] == "INTERVENE"
    assert "secret=yes" not in dashboard.profile_detail.toPlainText()


def test_category_preferences_and_learned_rule_reset(qtbot, ui_controller) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    email = dashboard.category_controls[DataCategory.EMAIL.value]
    email.setCurrentIndex(email.findData(Preference.ALWAYS_WARN.value))
    dashboard.save_preferences()
    assert ui_controller.core.preferences.categories["email"] == Preference.ALWAYS_WARN
    assert (
        ui_controller.core.store.get_preferences()["user"]["categories"]["email"] == "always_warn"
    )

    ui_controller.core.learned_rules.rules.append(
        LearnedRule(category=DataCategory.EMAIL, purpose="newsletter", consecutive_continue=3)
    )
    dashboard.reset_preferences()
    assert ui_controller.core.learned_rules.rules == []
    assert ui_controller.core.store.get_learned_rules()["user"]["rules"] == []


def test_export_import_and_requester_overrides(
    qtbot, ui_controller, tmp_path: Path, monkeypatch
) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    exported = tmp_path / "preferences.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args: (str(exported), "JSON (*.json)")
    )
    dashboard.export_preferences()
    assert json.loads(exported.read_text())["version"] == 1

    imported = tmp_path / "import.json"
    imported.write_text(
        json.dumps(
            {
                "version": 1,
                "preferences": {
                    "user": {
                        "categories": {"email": "reject"},
                        "requester_overrides": {"https://news.example": "usually_allow"},
                        "expected_permissions": {},
                        "clipboard_allowlist": ["safe.app"],
                        "reject_optional_cookies": False,
                    }
                },
                "learned_rules": {"user": {"rules": []}},
            }
        )
    )
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args: (str(imported), "JSON (*.json)")
    )
    dashboard.import_preferences()

    assert ui_controller.core.preferences.requester_overrides == {
        "https://news.example": "usually_allow"
    }
    assert ui_controller.clipboard.allowlist == ["safe.app"]
    assert ui_controller.settings.reject_optional_cookies is False


def test_invalid_import_warns_without_changing_preferences(
    qtbot, ui_controller, tmp_path: Path, monkeypatch
) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"version": 999}')
    warnings: list[str] = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(invalid), "JSON"))
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message)
    )
    original = ui_controller.core.preferences.model_copy(deep=True)
    dashboard.import_preferences()
    assert warnings
    assert ui_controller.core.preferences == original


def test_settings_route_llm_key_hotkey_autostart_and_retention(
    qtbot, ui_controller, monkeypatch
) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    keys: list[str] = []
    hotkeys: list[object] = []

    class Hotkey:
        def __init__(self, shortcut: str, callback) -> None:
            self.shortcut = shortcut
            hotkeys.append(self)

        def start(self) -> None:
            hotkeys.append("started")

        def stop(self) -> None:
            hotkeys.append("stopped")

    monkeypatch.setattr("privacy_guardian.llm.client.set_api_key", keys.append)
    monkeypatch.setattr("privacy_guardian.sensors.hotkey.GlobalHotkey", Hotkey)
    dashboard.api_key.setText("synthetic-key")
    dashboard.llm_enabled.setChecked(True)
    dashboard.llm_toggles["policy_refinement"].setChecked(False)
    dashboard.autostart.setChecked(False)
    dashboard.hotkey.setText("Ctrl+Alt+G")
    dashboard.retention.setValue(30)
    dashboard.save_settings()

    assert keys == ["synthetic-key"]
    assert dashboard.api_key.text() == ""
    assert ui_controller.settings.llm.enabled is True
    assert ui_controller.settings.llm.policy_refinement is False
    assert ui_controller.settings.hotkey == "Ctrl+Alt+G"
    assert ui_controller.core.adapter.autostart == [False]
    assert "started" in hotkeys


def test_keychain_error_is_visible_and_does_not_apply_settings(
    qtbot, ui_controller, monkeypatch
) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    warnings: list[str] = []

    def fail(_value: str) -> None:
        raise RuntimeError("synthetic keychain failure")

    monkeypatch.setattr("privacy_guardian.llm.client.set_api_key", fail)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message)
    )
    dashboard.api_key.setText("do-not-store")
    dashboard.autostart.setChecked(False)
    dashboard.save_settings()

    assert warnings
    assert ui_controller.settings.autostart is True
    assert ui_controller.core.adapter.autostart == []


def test_support_bundle_contains_diagnostics_but_no_event_pii(
    qtbot, ui_controller, tmp_path: Path, monkeypatch
) -> None:
    seed_history(ui_controller)
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    support = tmp_path / "support.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(support), "JSON"))
    dashboard.export_support()
    payload = support.read_text()
    assert '"version": "0.1.0"' in payload
    assert "one.example" not in payload
    assert "Decision for" not in payload


def test_profile_lookup_and_log_view_redact_sensitive_text(qtbot, ui_controller) -> None:
    ui_controller.core.store.put_profile("site", "https://profile.example", {"purpose": "news"})
    log = ui_controller.settings.data_dir / "logs/guardian.log"
    log.parent.mkdir()
    log.write_text("contact alice@example.com card 4111111111111111")
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.profile_key.setText("https://profile.example")
    dashboard.view_profile()
    dashboard.refresh()

    assert json.loads(dashboard.profile_detail.toPlainText()) == {"purpose": "news"}
    assert "alice@example.com" not in dashboard.log_view.toPlainText()
    assert "4111111111111111" not in dashboard.log_view.toPlainText()


def test_refresh_timer_follows_dashboard_visibility(qtbot, ui_controller) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    assert dashboard.timer.isActive() is False

    dashboard.show()
    qtbot.waitUntil(dashboard.timer.isActive)
    dashboard.hide()
    qtbot.waitUntil(lambda: not dashboard.timer.isActive())

    dashboard.show()
    qtbot.waitUntil(dashboard.timer.isActive)
    dashboard.close()
    qtbot.waitUntil(lambda: not dashboard.timer.isActive())


def test_the_model_picker_offers_suggestions_and_keeps_a_configured_one(
    qtbot, ui_controller
) -> None:
    """A hard-coded model list goes stale, so whatever is configured stays selectable."""
    ui_controller.settings.llm.model = "gemini-something-unreleased"
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    offered = [dashboard.model.itemText(index) for index in range(dashboard.model.count())]
    assert SUGGESTED_MODELS[0] in offered
    assert dashboard.model.currentText() == "gemini-something-unreleased"
    assert dashboard.model.isEditable()


def test_testing_the_model_asks_the_service_rather_than_blocking_the_window(
    qtbot, ui_controller
) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.api_key.setText("synthetic-key")
    dashboard.model.setCurrentText("gemini-2.5-flash")
    dashboard.test_llm()

    assert ("test_llm", "synthetic-key", "gemini-2.5-flash") in ui_controller.calls
    # The button stays down until an answer comes back, so it cannot be fired twice.
    assert dashboard.llm_test.isEnabled() is False
    assert dashboard.llm_status.text()


def test_a_successful_test_replaces_the_guesses_with_what_the_key_can_call(
    qtbot, ui_controller
) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.llm_enabled.setChecked(True)
    dashboard.show_llm_result(
        ConnectionCheck(
            ok=True,
            model="gemini-2.5-flash",
            latency_ms=412,
            models=["gemini-2.5-flash", "gemini-2.5-pro"],
        )
    )
    offered = [dashboard.model.itemText(index) for index in range(dashboard.model.count())]
    assert offered == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert dashboard.model.currentText() == "gemini-2.5-flash"
    assert "412" in dashboard.llm_status.text()
    assert dashboard.llm_test.isEnabled() is True


def test_a_failed_test_says_which_setting_to_change(qtbot, ui_controller) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.show_llm_result(ConnectionCheck(ok=False, reason="key_unavailable"))
    status = dashboard.llm_status.text()
    assert "API key" in status
    # The reason is in the reader's terms, never the provider's error code.
    assert "key_unavailable" not in status
    assert dashboard.llm_test.isEnabled() is True


def test_the_chosen_model_is_what_gets_saved(qtbot, ui_controller, monkeypatch) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    monkeypatch.setattr(
        "privacy_guardian.sensors.hotkey.GlobalHotkey", lambda *_: FakeGlobalHotkey()
    )
    dashboard.model.setCurrentText("gemini-2.5-pro")
    dashboard.save_settings()
    assert ui_controller.settings.llm.model == "gemini-2.5-pro"


class FakeGlobalHotkey:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def test_a_working_key_behind_an_unticked_box_says_so(qtbot, ui_controller) -> None:
    """The one outcome that looks like success and does nothing."""
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.llm_enabled.setChecked(False)
    dashboard.show_llm_result(ConnectionCheck(ok=True, model="gemini-2.5-flash", latency_ms=90))
    assert "still switched off" in dashboard.llm_status.text()


def test_a_failure_is_not_drawn_as_a_hint(qtbot, ui_controller) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.show_llm_result(ConnectionCheck(ok=False, reason="timeout"))
    assert dashboard.llm_status.property("role") == "warn"
    dashboard.llm_enabled.setChecked(True)
    dashboard.show_llm_result(ConnectionCheck(ok=True, model="gemini-2.5-flash", latency_ms=90))
    assert dashboard.llm_status.property("role") == "muted"


def test_sites_pane_is_a_report_not_a_json_console(qtbot, ui_controller) -> None:
    """Site and app memory is still kept, read and written — it just has no controls on
    a page whose job is to tell someone what a site does with their data."""
    from privacy_guardian.ui.dashboard import SECTIONS

    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    dashboard.select("sites_and_apps")
    pane = dashboard.stack.widget(SECTIONS.index("sites_and_apps"))

    shown = [label.text() for label in pane.findChildren(QLabel) if label.text()]
    assert "Site and app memory" not in shown
    assert [button.text() for button in pane.findChildren(QPushButton)] == ["Run thorough check"]
    assert not any(widget.isVisibleTo(pane) for widget in pane.findChildren(QTextEdit))
    assert not dashboard.profile_key.isVisibleTo(pane)

    # The memory itself is untouched: still loaded on refresh, still saveable.
    dashboard.refresh()
    assert json.loads(dashboard.memory.toPlainText())
    dashboard.save_memory()


def test_overview_is_the_landing_page_and_starts_honest_about_having_nothing(
    qtbot, ui_controller
) -> None:
    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    assert dashboard.current_section == "overview"
    assert "Nothing has been counted yet" in dashboard.tally_caption.text()
    assert all(value.text() == "0" for value, _ in dashboard.tally_tiles.values())
    assert dashboard.no_decisions.isVisibleTo(dashboard)
    # A nonsense section lands on the same page rather than the history table.
    dashboard.select("nowhere")
    assert dashboard.current_section == "overview"


def test_overview_tiles_say_what_was_counted_and_what_it_is_made_of(qtbot, ui_controller) -> None:
    """Each number on the Overview must be traceable to stored records, and the words
    under it must say what the number is made of rather than grade the app."""
    store = ui_controller.core.store
    site = Requester(origin="https://news.example", display_name="news.example")
    for _ in range(2):
        store.save_event(
            TrackingEvent(requester=site, tracker_domains=["ads.example", "pixel.example"])
        )
    upload = FileUploadEvent(requester=site)
    store.save_event(upload)
    store.save_decision(
        Decision(
            event_id=upload.id,
            outcome=Outcome.INTERVENE,
            risk=0.9,
            explanation="x",
            actions=["cancel"],
        )
    )
    store.save_response(UserResponse(event_id=upload.id, action="cancel"))
    banner = ConsentBannerEvent(requester=site, cmp="onetrust")
    store.save_event(banner)
    store.save_decision(
        Decision(
            event_id=banner.id,
            outcome=Outcome.INFORM,
            risk=0.3,
            explanation="x",
            actions=["reject_optional"],
            auto_action="reject_optional",
        )
    )
    store.save_response(UserResponse(event_id=banner.id, action="reject_optional"))
    store.cache_document(
        "https://news.example",
        "d" * 8,
        {"policy": {"missing": False}, "word_counts": {"policy": 230 * 75}},
    )

    dashboard = Dashboard(ui_controller)
    qtbot.addWidget(dashboard)
    text = {
        key: (value.text(), detail.text()) for key, (value, detail) in dashboard.tally_tiles.items()
    }
    assert text["requesters"] == ("1", "1 site  ·  0 apps")
    assert text["trackers"] == ("2", "2 networks across 1 site")
    assert text["files"] == ("1", "1 held sensitive information")
    assert text["documents"] == ("1", "About 1 h 15 min of reading")
    assert text["banners"] == ("1", "On 1 site")
    assert text["permissions"] == ("0", "0 grants across 0 apps")
    assert dashboard.tally_caption.text().startswith("Since ")
    assert "Counted on this device" in dashboard.tally_caption.text()

    shown = [label.text() for label in dashboard.findChildren(QLabel) if label.text()]
    assert "Optional cookies rejected" in shown
    assert "1 automatic" in shown
    assert "Not shared" in shown
    # Only what was decided is listed; a row of zeros would say nothing.
    assert "Redacted copies created" not in shown
    assert not dashboard.no_decisions.isVisibleTo(dashboard)
    # The word the user asked never to see.
    assert not any("help" in label.lower() for label in shown)
