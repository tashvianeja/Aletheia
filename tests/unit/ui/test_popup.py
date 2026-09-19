from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel

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
    assert popup._resolved is True


def test_widgets_stay_up_until_they_are_answered(qtbot) -> None:
    """A warning that removes itself is one the person may never finish reading."""
    actions: list[tuple[str, str, bool]] = []
    intervene = InterventionPopup(decision(), lambda *args: actions.append(args))
    inform = InterventionPopup(decision("inform", Outcome.INFORM))
    qtbot.addWidget(intervene)
    qtbot.addWidget(inform)
    intervene.show()
    inform.show()

    # Long enough that the old eight-second toast would have gone.
    qtbot.wait(300)

    assert intervene.isVisible() and inform.isVisible()
    assert not actions
    assert not any(
        isinstance(child, QTimer) and child.isActive() and child.interval() >= 1_000
        for child in intervene.findChildren(QTimer) + inform.findChildren(QTimer)
    ), "nothing may be counting down towards dismissing the widget"


def test_informational_card_can_be_closed_and_closing_it_does_nothing_else(qtbot) -> None:
    actions: list[tuple[str, str, bool]] = []
    inform = InterventionPopup(
        decision("inform", Outcome.INFORM), lambda *args: actions.append(args)
    )
    qtbot.addWidget(inform)
    inform.show()

    assert inform.card.close_button is not None, "a card that never expires needs a way out"
    qtbot.mouseClick(inform.card.close_button, Qt.MouseButton.LeftButton)

    assert not inform.isVisible()
    assert actions == [("inform", "cancel", False)]


def test_closing_a_desktop_notice_does_not_act_on_the_person_s_behalf(qtbot) -> None:
    """Dismissing a permission notice must not open system settings by itself."""
    from privacy_guardian.core.events import DataCategory, PermissionRequestEvent, Requester
    from privacy_guardian.engine.decision import decide

    notice = decide(
        PermissionRequestEvent(
            source="os",
            requester=Requester(kind="application", bundle_id="com.synthetic.grabber"),
            data_categories=[DataCategory.CAMERA],
            permission="camera",
            state="requested",
        )
    )
    chosen: list[tuple[str, str, bool]] = []
    popup = InterventionPopup(notice, lambda *args: chosen.append(args))
    qtbot.addWidget(popup)

    assert popup.dismiss_action() == "continue"
    popup.dismiss()

    assert [action for _id, action, _remember in chosen] == ["continue"]


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
    assert "#1c1f26" in popup.styleSheet()
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


def test_a_notice_is_not_given_a_green_tick_it_has_not_earned(qtbot) -> None:
    """A tick beside "is asking for your camera" says the opposite of the sentence."""
    from privacy_guardian.ui import icons

    notice = decision("notice", Outcome.INFORM).model_copy(update={"risk": 0.45})
    settled = decision("settled", Outcome.INFORM).model_copy(update={"risk": 0.1})
    for popup, expected in (
        (InterventionPopup(notice), "info"),
        (InterventionPopup(settled), "ok"),
    ):
        qtbot.addWidget(popup)
        glyphs = [
            label
            for label in popup.card.findChildren(QLabel)
            if not label.text() and not label.pixmap().isNull()
        ]
        wanted = icons.pixmap(
            expected, popup.card.colors["ok" if expected == "ok" else "faint"], 15
        )
        assert any(label.pixmap().toImage() == wanted.toImage() for label in glyphs), (
            f"expected the {expected} glyph beside the headline"
        )


def test_queue_gives_way_to_the_thorough_check_and_resumes_after_it(qtbot, ui_controller) -> None:
    """The card that is up is closed as its own close control would close it; the ones
    that have not been shown yet wait rather than landing under the check card."""
    queue = PopupQueue(ui_controller)
    qtbot.addWidget(queue)
    queue.enqueue(decision("first"))
    queue.enqueue(decision("second"))
    assert queue.current is not None and queue.current.decision.event_id == "first"

    queue.hold()
    queue.dismiss_current()

    assert ("response", "first", "cancel", False) in ui_controller.calls
    qtbot.wait(20)
    assert queue.current is None, "nothing takes the corner while the check card is up"
    assert [item.event_id for item in queue.queue] == ["second"]

    queue.release()
    qtbot.waitUntil(
        lambda: queue.current is not None and queue.current.decision.event_id == "second"
    )
    queue.current.dismiss()


def test_desktop_surfaces_stay_up_while_the_app_is_inactive(qtbot) -> None:
    popup = InterventionPopup(decision())
    qtbot.addWidget(popup)
    assert popup.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert popup.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    from privacy_guardian.ui.popup import ConfirmationBar

    bar = ConfirmationBar("3 fields marked as not needed")
    qtbot.addWidget(bar)
    assert bar.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    finished = []
    bar.done.connect(lambda: finished.append(True))
    bar.dismiss()
    bar.dismiss()
    assert finished == [True], "dismissing twice reports once and never touches a dead bar"
