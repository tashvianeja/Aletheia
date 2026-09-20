from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

from aletheia.ui.deepcheck import DeepCheckWindow
from aletheia.ui.onboarding import Onboarding


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
    monkeypatch.setattr("aletheia.util.installation.install", installed.append)
    monkeypatch.setattr("aletheia.llm.client.set_api_key", keys.append)
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
        "aletheia.llm.client.set_api_key",
        lambda _value: (_ for _ in ()).throw(RuntimeError("keychain unavailable")),
    )
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message)
    )
    monkeypatch.setattr(
        "aletheia.util.installation.install",
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
    from aletheia.deepcheck import build_groups

    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)

    # While running it is a bar and one line about what is being checked, not a list.
    assert set(window.stage_states) == {"permissions", "tracking", "policy", "forms"}
    running = _labels(window)
    assert "Getting ready…" in running and "0 of 4" in running
    assert "Privacy policy" not in running, "the four sections are the bar, not a list"
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
            "summary": "Overall: 1 thing to review",
            "origin": "dropcrate.example",
            "findings": findings,
            "checked": checked,
            "groups": build_groups(findings, checked),
            "context_available": True,
        }
    )
    labels = _labels(window)

    assert window.status.text() == "Overall: 1 thing to review"
    assert "Advertising profile" in labels
    assert "Your activity may be used for personalised advertising." in labels
    assert "dropcrate.example" in labels
    assert {"Done", "View full analysis"} <= set(labels)
    # Only what needs looking at. The all-clear lines stay in the full report.
    assert "No sensitive file currently shared" not in labels
    assert "No advertising profile detected" not in labels


def test_deep_check_card_lists_nothing_when_there_is_nothing_to_review(
    qtbot, ui_controller
) -> None:
    from aletheia.deepcheck import build_groups

    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    checked = [{"kind": kind, "available": True, "clean": True} for kind in ("tracking", "forms")]

    window.show_report(
        {
            "summary": "Nothing to review",
            "origin": "dropcrate.example",
            "findings": [],
            "checked": checked,
            "groups": build_groups([], checked),
            "context_available": True,
        }
    )
    labels = _labels(window)

    assert window.status.text() == "Nothing to review"
    assert not any("No " in label for label in labels), labels


def test_deep_check_card_caps_the_list_and_points_at_the_full_report(qtbot, ui_controller) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    findings = [
        {"kind": "tracking", "severity": "INFORM", "summary": f"Finding {index}", "detail": ""}
        for index in range(8)
    ]

    window.show_report(
        {
            "summary": "Overall: 8 things to review",
            "origin": "dropcrate.example",
            "findings": findings,
            "checked": [],
            "groups": [],
            "context_available": True,
        }
    )
    labels = _labels(window)

    assert "Finding 0" in labels and "Finding 4" in labels
    assert "Finding 5" not in labels
    assert "3 more in the full analysis" in labels


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
    monkeypatch.setattr("aletheia.util.installation.install", lambda _settings: [])
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


def _button(window: DeepCheckWindow, text: str) -> QPushButton:
    return next(b for b in window.findChildren(QPushButton) if b.text() == text)


def test_deep_check_card_is_a_non_activating_panel_that_stays_up(qtbot, ui_controller) -> None:
    """The bug this guards: on macOS a click on Done only activated the app, and the card
    then vanished with the app's next deactivation, so neither button ever fired."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    assert window.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert window.windowFlags() & Qt.WindowType.Tool
    assert window.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_deep_check_done_button_closes_the_card_when_clicked(qtbot, ui_controller) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()
    window.show_report({"summary": "Nothing to review", "findings": [], "groups": []})
    dismissed = []
    window.dismissed.connect(lambda: dismissed.append(True))

    qtbot.mouseClick(_button(window, "Done"), Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: not window.isVisible())
    assert dismissed, "the controller is told the card has gone"
    assert not [call for call in ui_controller.calls if call[0] in {"report", "dashboard"}]


def test_deep_check_full_analysis_button_opens_the_report_when_clicked(
    qtbot, ui_controller
) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()
    report = {"summary": "2 things to review", "findings": [], "groups": []}
    window.show_report(report)

    qtbot.mouseClick(_button(window, "View full analysis"), Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: not window.isVisible())
    assert ("report", report) in ui_controller.calls


def _report(origin: str) -> dict[str, object]:
    return {
        "summary": "Overall: 1 thing to review",
        "origin": origin,
        "findings": [{"kind": "tracking", "severity": "INFORM", "summary": "Advertising profile"}],
        "groups": [],
        "context_available": True,
    }


def test_the_check_card_goes_when_the_browser_moves_to_another_page(qtbot, ui_controller) -> None:
    """The bug this guards: a check card left up over the next tab kept showing the last
    tab's findings, which reads as a verdict on a page that was never checked."""
    ui_controller.core.active_origin = "https://shop.test"
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()
    window.show_report(_report("https://shop.test"))

    window.page_changed("https://bank.test")

    qtbot.waitUntil(lambda: not window.isVisible())


def test_the_check_card_stays_up_for_the_page_it_is_about(qtbot, ui_controller) -> None:
    ui_controller.core.active_origin = "https://shop.test"
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()
    window.show_report(_report("https://shop.test"))

    # The same page again, and a browser showing no page at all — neither is a reason
    # to take the card away from someone who may be part-way through reading it.
    window.page_changed("https://shop.test")
    window.page_changed("")

    assert window.isVisible()


def test_a_check_about_a_desktop_application_ignores_the_browser_behind_it(
    qtbot, ui_controller
) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()
    window.show_report(_report("Photos"))

    window.page_changed("https://bank.test")

    assert window.isVisible()


def test_a_check_that_has_not_found_its_page_yet_is_not_taken_down(qtbot, ui_controller) -> None:
    """Nothing known about the page means nothing known about whether it has changed."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()

    window.page_changed("https://bank.test")

    assert window.isVisible()


def test_a_rerun_check_forgets_the_page_the_last_one_was_about(qtbot, ui_controller) -> None:
    ui_controller.core.active_origin = "https://shop.test"
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show_report(_report("https://shop.test"))

    ui_controller.core.active_origin = "https://bank.test"
    window._show_running()

    assert window.report is None
    assert window.origin == "https://bank.test"
    assert "https://bank.test" in _labels(window)


def test_the_running_check_shows_each_part_starting_rather_than_only_finishing(
    qtbot, ui_controller
) -> None:
    """The bug this guards: every part of a run reported only when it was over, and the
    parts that take seconds all report within a moment of each other at the end, so the
    bar would sit at nothing and then fill in at once, telling the person nothing about
    whether it is working."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)

    assert set(window.stage_states.values()) == {"pending"}
    assert window.steps is not None and window.steps.value() == 0

    window.show_progress({"stage": "tracking", "state": "running"})
    window.show_progress({"stage": "policy", "state": "running"})

    assert window.stage_states["tracking"] == "running"
    assert window.stage_states["policy"] == "running"
    assert window.stage_states["permissions"] == "pending", "nothing claims to be under way early"
    assert window.steps.value() == 0, "starting is not finishing"

    window.show_progress({"stage": "tracking", "state": "done"})
    window.show_progress({"stage": "policy", "state": "unavailable"})
    window.show_progress({"stage": "permissions", "state": "running"})

    assert window.stage_states["tracking"] == "done"
    assert window.stage_states["policy"] == "unavailable"
    assert window.stage_states["permissions"] == "running"
    # A part that cannot be answered here has stopped moving too, so the bar counts it.
    assert window.steps.value() == 2
    assert window.tally is not None and window.tally.text() == "2 of 4"


def test_a_part_is_answered_by_whichever_step_behind_it_answers_first(qtbot, ui_controller) -> None:
    """Tracking covers the trackers and the cookie banner. A page with a banner and no
    trackers has still been checked for tracking, so the bar may not give the count
    back because the second step behind it reported later."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)

    window.show_progress({"stage": "tracking", "state": "done"})
    window.show_progress({"stage": "consent", "state": "running"})

    assert window.stage_states["tracking"] == "done"


def test_the_mark_beside_the_line_keeps_turning_and_then_stops(qtbot, ui_controller) -> None:
    """Motion is the whole point: a bar that moves four times in a run is still for
    seconds at a stretch, and a still card is indistinguishable from a stuck one. It
    also has to stop, because a card that spins after it has finished is lying."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()

    assert window.spinner.isActive(), "the card is up, so the run is under way"
    qtbot.waitUntil(lambda: window._turn > 0, timeout=2_000)
    turned = window._turn
    qtbot.waitUntil(lambda: window._turn != turned, timeout=2_000)

    for stage in ("tracking", "consent", "policy", "terms", "forms", "uploads", "permissions"):
        window.show_progress({"stage": stage, "state": "done"})

    assert window.steps is not None and window.steps.value() == 4
    assert window.spinner.isActive(), "four of four answered, but the run is still going"

    window.show_progress({"stage": "complete", "state": "done"})

    assert not window.spinner.isActive(), "nothing turns once the run says it is over"


def test_the_running_check_says_what_it_is_doing_now(qtbot, ui_controller) -> None:
    """The line above the bar is all the person gets now that the list has gone, so it
    has to name what is being checked at each point — including the two longest waits,
    collecting the page and writing the summary, which the bar cannot count."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    assert window.activity is not None

    window.show_progress({"stage": "start", "state": "running"})
    assert window.activity.text() == "Getting ready…"
    window.show_progress({"stage": "tracking", "state": "running"})
    assert window.activity.text() == "Checking trackers, policies and forms…"
    window.show_progress({"stage": "permissions", "state": "running"})
    assert window.activity.text() == "Checking application permissions…"

    for stage in ("tracking", "consent", "policy", "terms", "forms", "uploads", "permissions"):
        window.show_progress({"stage": stage, "state": "done"})
    window.show_progress({"stage": "summary", "state": "running"})

    assert window.activity.text() == "Writing the summary…"
    assert window.steps is not None and window.steps.maximum() == 0, (
        "nothing left to count and no way to know how long: the bar says busy, not done"
    )
    assert window.tally is not None and window.tally.text() == "", (
        "four of four beside a busy bar would say the run had already finished"
    )


def test_a_rerun_starts_the_bar_over_and_leaves_nothing_turning(qtbot, ui_controller) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()
    window.show_progress({"stage": "tracking", "state": "running"})
    assert window.spinner.isActive()

    window.show_report({"summary": "Nothing to review", "findings": [], "groups": []})

    assert not window.spinner.isActive(), "the card the spinner was drawing on has gone"
    assert window.steps is None and window.activity is None

    window._show_running()

    assert set(window.stage_states.values()) == {"pending"}
    assert window.steps is not None and window.steps.value() == 0
    assert window.tally is not None and window.tally.text() == "0 of 4"
    assert window.activity is not None and window.activity.text() == "Getting ready…"


def test_a_check_card_taken_down_mid_run_leaves_nothing_turning(qtbot, ui_controller) -> None:
    """The browser moving to another page takes the card away while the run carries on
    reporting in. Nothing is left animating a card nobody can see."""
    ui_controller.core.active_origin = "https://shop.test"
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show()
    window.show_progress({"stage": "tracking", "state": "running"})
    assert window.spinner.isActive()

    window.show_report(_report("https://shop.test"))
    window.page_changed("https://bank.test")
    qtbot.waitUntil(lambda: not window.isVisible())
    window.show_progress({"stage": "permissions", "state": "running"})

    assert not window.spinner.isActive()


def test_progress_arriving_after_the_result_is_ignored(qtbot, ui_controller) -> None:
    """A late report from a step that had already timed out must not redraw a card
    that is now showing the answer."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    window.show_report({"summary": "Nothing to review", "findings": [], "groups": []})

    window.show_progress({"stage": "permissions", "state": "done"})
    window.show_progress("start")

    assert window.status.text() == "Nothing to review"
