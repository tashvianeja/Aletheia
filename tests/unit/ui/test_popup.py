from __future__ import annotations

from PySide6.QtCore import Qt

from privacy_guardian.core.events import Decision, Outcome
from privacy_guardian.ui.popup import InterventionPopup, PopupQueue


def decision(event_id: str = "event-1", outcome: Outcome = Outcome.INTERVENE) -> Decision:
    return Decision(
        event_id=event_id,
        outcome=outcome,
        risk=0.9,
        explanation="A document contains identity information.",
        rationale=["Identity data is unnecessary for image compression."],
        actions=["cancel", "continue", "redact"],
        default_action="cancel",
    )


def test_popup_buttons_emit_action_and_remember(qtbot) -> None:
    selected: list[tuple[str, str, bool]] = []
    popup = InterventionPopup(decision(), lambda *args: selected.append(args))
    qtbot.addWidget(popup)
    popup.remember.setChecked(True)

    qtbot.mouseClick(popup.buttons["redact"], Qt.MouseButton.LeftButton)

    assert selected == [("event-1", "redact", True)]
    assert not popup.timer.isActive()
    assert popup._resolved is True


def test_popup_uses_safe_timeout_and_inform_dismissal(qtbot) -> None:
    intervene_actions: list[tuple[str, str, bool]] = []
    intervene = InterventionPopup(decision(), lambda *args: intervene_actions.append(args))
    inform = InterventionPopup(decision("inform", Outcome.INFORM))
    qtbot.addWidget(intervene)
    qtbot.addWidget(inform)

    assert intervene.timer.interval() == 60_000
    assert inform.timer.interval() == 8_000
    intervene.timeout()
    inform.timeout()

    assert intervene_actions == [("event-1", "cancel", False)]
    assert inform._resolved is True
    assert not inform.isVisible()


def test_escape_selects_default_action(qtbot) -> None:
    selected: list[tuple[str, str, bool]] = []
    popup = InterventionPopup(decision(), lambda *args: selected.append(args))
    qtbot.addWidget(popup)
    popup.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
    popup.show()
    popup.activateWindow()

    qtbot.keyClick(popup, Qt.Key.Key_Escape)

    assert selected == [("event-1", "cancel", False)]


def test_popup_does_not_take_initial_focus_and_supports_theme_and_keyboard(qtbot) -> None:
    popup = InterventionPopup(decision())
    qtbot.addWidget(popup)

    assert popup.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert popup.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    popup.set_theme("light")
    light = popup.styleSheet()
    assert "#ffffff" in light
    popup.set_theme("dark")
    assert popup.styleSheet() != light
    assert "#202329" in popup.styleSheet()
    assert all(button.accessibleName() for button in popup.buttons.values())


def test_queue_orders_updates_and_skips_stale_decisions(qtbot, ui_controller) -> None:
    queue = PopupQueue(ui_controller)
    qtbot.addWidget(queue)
    first = decision("first")
    updated = first.model_copy(update={"explanation": "Updated explanation"})
    second = decision("second")

    queue.enqueue(first)
    queue.enqueue(second)
    queue.enqueue(updated)
    assert queue.current is not None
    assert queue.current.explanation.text() == "Updated explanation"
    assert [item.event_id for item in queue.queue] == ["second"]

    ui_controller.core.actions["first"] = {"action": "cancel"}
    queue._reconcile()
    qtbot.waitUntil(
        lambda: queue.current is not None and queue.current.decision.event_id == "second"
    )
    queue.current.choose("continue")
    assert ("response", "second", "continue", False) in ui_controller.calls


def test_queue_ignores_ignore_outcomes(qtbot, ui_controller) -> None:
    queue = PopupQueue(ui_controller)
    qtbot.addWidget(queue)
    queue.enqueue(decision(outcome=Outcome.IGNORE))
    assert queue.current is None
    assert not queue.queue
