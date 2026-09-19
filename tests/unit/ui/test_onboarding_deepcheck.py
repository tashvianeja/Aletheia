from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QPushButton

from privacy_guardian.ui.deepcheck import DeepCheckWindow
from privacy_guardian.ui.onboarding import Onboarding


def test_onboarding_has_complete_walkthrough_and_live_permission_status(
    qtbot, ui_controller
) -> None:
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)

    assert onboarding.pageIds() == [0, 1, 2, 3, 4]
    assert onboarding.permission_status is not None
    assert "unavailable" in onboarding.permission_status.text().lower()
    permission_page = onboarding.page(1)
    buttons = permission_page.findChildren(QPushButton)
    buttons[0].click()
    assert ("open_settings", "full_disk") in ui_controller.calls


def test_onboarding_finish_persists_cloud_and_autostart(qtbot, ui_controller, monkeypatch) -> None:
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    installed: list[object] = []
    keys: list[str] = []
    monkeypatch.setattr("privacy_guardian.util.installation.install", installed.append)
    monkeypatch.setattr("privacy_guardian.llm.client.set_api_key", keys.append)
    onboarding.cloud_enabled.setChecked(True)
    onboarding.key_input.setText("synthetic-key")
    onboarding.autostart.setChecked(False)
    onboarding._finish()

    assert keys == ["synthetic-key"]
    assert installed == [ui_controller.settings]
    assert ui_controller.settings.llm.enabled is True
    assert ui_controller.settings.autostart is False
    assert ui_controller.settings.onboarding_complete is True


def test_onboarding_keychain_failure_is_visible(qtbot, ui_controller, monkeypatch) -> None:
    ui_controller.settings.onboarding_complete = False
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    warnings: list[str] = []
    monkeypatch.setattr(
        "privacy_guardian.llm.client.set_api_key",
        lambda _value: (_ for _ in ()).throw(RuntimeError("keychain unavailable")),
    )
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message)
    )
    monkeypatch.setattr(
        "privacy_guardian.util.installation.install",
        lambda _settings: (_ for _ in ()).throw(AssertionError("must not install")),
    )
    onboarding.key_input.setText("synthetic-key")
    onboarding._finish()
    assert warnings
    assert ui_controller.settings.onboarding_complete is False


def test_deep_check_renders_findings_clean_unavailable_and_missing_context(
    qtbot, ui_controller
) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show_report(
        {
            "summary": "2 things to review",
            "findings": [{"summary": "Advertising profile"}],
            "checked": [
                {"kind": "forms", "available": True, "clean": True},
                {"kind": "screen", "available": False, "clean": False},
            ],
            "context_available": False,
        }
    )
    rows = [window.results.item(index).text() for index in range(window.results.count())]
    assert window.progress.maximum() == 1
    assert window.status.text() == "2 things to review"
    assert any("Advertising profile" in row for row in rows)
    assert any(row.startswith("✓") for row in rows)
    assert any(row.startswith("○") for row in rows)
    assert any("context" in row.lower() for row in rows)
