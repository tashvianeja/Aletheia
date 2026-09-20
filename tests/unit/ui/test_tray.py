from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon

from privacy_guardian.ui.tray import GuardianTray, shield_icon


def test_tray_exposes_and_routes_all_actions(qtbot, ui_controller) -> None:
    tray = GuardianTray(ui_controller)

    expected = {
        "deep_check",
        "pause_hour",
        "pause_tomorrow",
        "resume",
        "recent",
        "dashboard",
        "settings",
        "permissions",
        "extensions",
        "onboarding",
        "updates",
        "quit",
    }
    assert set(tray.actions) == expected
    for action in tray.actions.values():
        action.trigger()

    assert ("deep_check",) in ui_controller.calls
    assert ("pause", 3600) in ui_controller.calls
    assert ("pause", 86400) in ui_controller.calls
    assert ("pause", 0) in ui_controller.calls
    assert ("dashboard", "settings") in ui_controller.calls
    assert ("quit",) in ui_controller.calls
    tray.hide()
    tray.deleteLater()


def test_double_click_runs_deep_check_and_states_have_icons(qtbot, ui_controller) -> None:
    tray = GuardianTray(ui_controller)
    tray._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    assert ui_controller.calls[-1] == ("deep_check",)
    for state in ("idle", "attention", "paused"):
        tray.set_state(state)
        assert not tray.icon().isNull()
        assert not shield_icon(state).isNull()
    tray.hide()
    tray.deleteLater()
