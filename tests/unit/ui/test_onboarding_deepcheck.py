from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

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
    # Setup only counts as complete once the extension is really connected.
    ui_controller.browsers = ["chromium"]
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    onboarding.extension_page.registered = True
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


def advance(wizard, qtbot) -> int:
    """Click Next the way a person would, and report how far it got."""
    clicks = 0
    while wizard.button(wizard.WizardButton.NextButton).isEnabled() and clicks < 10:
        qtbot.mouseClick(wizard.button(wizard.WizardButton.NextButton), Qt.MouseButton.LeftButton)
        clicks += 1
    return clicks


def texts(widget) -> list[str]:
    return [label.text() for label in widget.findChildren(QLabel) if label.text()]


def test_setup_stops_until_a_browser_extension_is_actually_connected(qtbot, ui_controller) -> None:
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    onboarding.show()

    advance(onboarding, qtbot)

    assert onboarding.currentPage() is onboarding.extension_page
    assert not onboarding.button(onboarding.WizardButton.NextButton).isEnabled()
    assert not onboarding.button(onboarding.WizardButton.FinishButton).isEnabled()
    assert any("waiting" in text.lower() for text in texts(onboarding.extension_page.connection))


def test_setup_registers_the_bridge_before_asking_for_the_extension(qtbot, ui_controller) -> None:
    """The extension cannot connect to a bridge that has not been written yet."""
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    onboarding.show()

    advance(onboarding, qtbot)

    assert ("register_bridge",) in ui_controller.calls
    assert onboarding.extension_page.registered is True
    assert "registered" in onboarding.extension_page.bridge_status.text().lower()
    assert str(ui_controller.extension_folder()) == onboarding.extension_page.path_field.text()


def test_setup_continues_once_a_browser_connects(qtbot, ui_controller) -> None:
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    onboarding.show()
    advance(onboarding, qtbot)

    ui_controller.browsers = ["chromium"]
    onboarding.extension_page.refresh()

    assert onboarding.button(onboarding.WizardButton.NextButton).isEnabled()
    assert any("chromium" in text for text in texts(onboarding.extension_page.connection))
    advance(onboarding, qtbot)
    assert onboarding.currentId() == onboarding.pageIds()[-1]
    assert any("chromium" in text for text in texts(onboarding.pages["finish"].summary))


def test_a_failed_bridge_registration_is_explained_and_blocks(qtbot, ui_controller) -> None:
    ui_controller.bridge_result = (False, "No supported browser profile was found.")
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    onboarding.show()

    advance(onboarding, qtbot)

    assert onboarding.extension_page.registered is False
    assert "No supported browser" in onboarding.extension_page.bridge_status.text()
    assert not onboarding.button(onboarding.WizardButton.NextButton).isEnabled()


def test_skipping_the_extension_is_deliberate_and_leaves_setup_incomplete(
    qtbot, ui_controller, monkeypatch
) -> None:
    monkeypatch.setattr("privacy_guardian.util.installation.install", lambda _settings: [])
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    onboarding = Onboarding(ui_controller)
    qtbot.addWidget(onboarding)
    onboarding.show()
    advance(onboarding, qtbot)

    # Cancelling the confirmation leaves the walkthrough exactly where it was.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel
    )
    onboarding.extension_page.skip.click()
    assert not onboarding.button(onboarding.WizardButton.NextButton).isEnabled()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    onboarding.extension_page.skip.click()

    assert onboarding.button(onboarding.WizardButton.NextButton).isEnabled()
    advance(onboarding, qtbot)
    summary = texts(onboarding.pages["finish"].summary)
    assert any("No browser extension connected" in line for line in summary)
    onboarding._finish()
    assert ui_controller.settings.onboarding_complete is False, (
        "a skipped setup must keep prompting rather than claim to be ready"
    )
