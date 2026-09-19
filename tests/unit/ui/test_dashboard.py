from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from privacy_guardian.core.events import DataCategory, Decision, Outcome, PrivacyEvent, Requester
from privacy_guardian.engine.preferences import LearnedRule, Preference
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
    assert dashboard.history.rowCount() == 2

    dashboard.requester_filter.setText("https://one.example")
    assert dashboard.history.rowCount() == 1
    dashboard.outcome_filter.setCurrentText("INTERVENE")
    assert dashboard.history.rowCount() == 1
    dashboard.show_event_detail(0, 0)

    assert dashboard.tabs.currentIndex() == 3
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
