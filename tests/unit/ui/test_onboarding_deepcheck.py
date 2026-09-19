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


def _labels(window) -> list[str]:
    from PySide6.QtWidgets import QLabel

    widgets = window.card.findChildren(QLabel) + window.card.findChildren(QPushButton)
    return [widget.text() for widget in widgets if widget.text()]


def test_deep_check_progresses_then_renders_grouped_result(qtbot, ui_controller) -> None:
    from privacy_guardian.deepcheck import build_groups

    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)

    # While running it is a checklist of the four sections.
    assert set(window.stage_glyphs) == {"permissions", "tracking", "policy", "forms"}
    assert "Privacy policy" in _labels(window)
    window.show_progress({"stage": "tracking", "state": "done"})

    findings = [
        {
            "kind": "tracking",
            "severity": "INFORM",
            "summary": "Advertising profile",
            "detail": "Your activity may be used for personalised advertising.",
        }
    ]
    checked = [
        {"kind": "tracking", "available": True, "clean": False},
        {"kind": "forms", "available": True, "clean": True},
        {"kind": "policy", "available": False, "clean": False},
    ]
    window.show_report(
        {
            "summary": "Overall: 1 things to review",
            "origin": "dropcrate.example",
            "findings": findings,
            "checked": checked,
            "groups": build_groups(findings, checked),
            "context_available": True,
        }
    )
    labels = _labels(window)

    assert window.status.text() == "Overall: 1 things to review"
    assert "Advertising profile" in labels
    assert "Your activity may be used for personalised advertising." in labels
    assert "No sensitive file currently shared" in labels
    assert "dropcrate.example" in labels
    assert {"Done", "View full analysis"} <= set(labels)


def test_deep_check_full_analysis_opens_the_report(qtbot, ui_controller) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    report = {
        "summary": "Nothing to review",
        "findings": [],
        "groups": [],
        "context_available": True,
    }
    window.show_report(report)
    window._open_full()
    assert ("report", report) in ui_controller.calls


def test_deep_check_without_context_says_so(qtbot, ui_controller) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show_report(
        {"summary": "Nothing to review", "findings": [], "groups": [], "context_available": False}
    )
    assert any("context" in label.lower() for label in _labels(window))
