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


def test_a_notice_offers_the_way_out_as_a_button_and_not_only_as_a_cross(qtbot) -> None:
    """The bug this guards: a card with nothing to decide had no button at all, so the
    only way to put it down was the cross in its corner — which reads as a card still
    waiting for an answer nobody can find. OK is that cross, spelled out, and the two
    have to record the same thing or the card offers two exits that mean different things."""
    by_button: list[tuple[str, str, bool]] = []
    by_cross: list[tuple[str, str, bool]] = []
    with_button = InterventionPopup(
        decision("inform", Outcome.INFORM), lambda *args: by_button.append(args)
    )
    with_cross = InterventionPopup(
        decision("inform", Outcome.INFORM), lambda *args: by_cross.append(args)
    )
    qtbot.addWidget(with_button)
    qtbot.addWidget(with_cross)
    with_button.show()
    with_cross.show()

    ok = with_button.buttons["acknowledge"]
    assert ok.text() == "OK" and ok.accessibleName() == "OK"
    qtbot.mouseClick(ok, Qt.MouseButton.LeftButton)
    assert with_cross.card.close_button is not None
    qtbot.mouseClick(with_cross.card.close_button, Qt.MouseButton.LeftButton)

    assert not with_button.isVisible()
    assert by_button == by_cross == [("inform", "cancel", False)]


def test_a_card_that_asks_for_a_decision_is_not_given_an_ok_button(qtbot) -> None:
    """An OK beside "Don't share" and "Upload anyway" would be a third answer to a
    question that has two, and no way to know which one it gave."""
    popup = InterventionPopup(decision())
    qtbot.addWidget(popup)

    assert "acknowledge" not in popup.buttons
    assert set(popup.buttons) == {"cancel", "continue", "redact"}


def test_the_reasoning_on_a_notice_opens_inside_the_card(qtbot) -> None:
    """The bug this guards: "Don't ask again" was never put into the notice's card, so
    it was a window in its own right, and opening the reasoning dropped a stray tick
    box in the middle of the screen."""
    notice = decision("inform", Outcome.INFORM)
    popup = InterventionPopup(notice)
    qtbot.addWidget(popup)
    popup.show()

    assert popup.card.why_button is not None, "a notice with reasoning offers to show it"
    assert popup.remember.isVisible() is False
    qtbot.mouseClick(popup.card.why_button, Qt.MouseButton.LeftButton)

    assert popup.remember.parent() is not None
    assert popup.remember.window() is popup, "nothing on the card may open a window of its own"
    assert popup.rationale.isVisible() and popup.remember.isVisible()


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
    """A green "All clear" beside "is asking for your camera" says the opposite of
    the sentence; a notice that carries any risk is amber, and only a settled one green."""
    notice = decision("notice", Outcome.INFORM).model_copy(update={"risk": 0.45})
    settled = decision("settled", Outcome.INFORM).model_copy(update={"risk": 0.1})
    for popup, expected, word in (
        (InterventionPopup(notice), "heads_up", "Heads up"),
        (InterventionPopup(settled), "all_clear", "All clear"),
    ):
        qtbot.addWidget(popup)
        assert popup.card.urgency == expected
        assert popup.card.band_label is not None and popup.card.band_label.text() == word


def test_the_band_says_in_words_what_its_colour_says(qtbot) -> None:
    """Every card wears its tier: the outline, the band and the word on it agree, and
    a decision built without a tier is given one rather than a blank band."""
    from privacy_guardian.ui.theme import URGENCY_LIGHT

    stop = InterventionPopup(decision("stop"), mode="light")  # INTERVENE at risk 0.9
    ask = InterventionPopup(decision("ask").model_copy(update={"risk": 0.5}), mode="light")
    qtbot.addWidget(stop)
    qtbot.addWidget(ask)

    assert stop.card.urgency == "act_now" and stop.card.property("urgency") == "act_now"
    assert stop.card.band_label is not None and stop.card.band_label.text() == "Act now"
    assert ask.card.urgency == "attention"
    assert ask.card.band_label is not None and ask.card.band_label.text() == "Needs your attention"
    assert URGENCY_LIGHT["act_now"]["band"] != URGENCY_LIGHT["attention"]["band"], (
        "the two red tiers must be told apart at a glance"
    )
    # The band keeps its natural height so the rows underneath are never squeezed.
    assert (
        stop.card.band is not None
        and stop.card.band.maximumHeight() == stop.card.band.minimumHeight()
    )


def test_an_informational_card_still_lists_what_was_found(qtbot) -> None:
    """The headline says "building an advertising profile"; the rows say which trackers.
    Dropping the rows from a notice left the person with the conclusion but no evidence."""
    from privacy_guardian.core.events import DecisionFinding

    notice = decision("rows", Outcome.INFORM).model_copy(
        update={
            "findings": [DecisionFinding(label="Shares what you do here with 4 other companies")],
            "subject": "This page",
            "destination": "dailymeridian.example",
        }
    )
    popup = InterventionPopup(notice)
    qtbot.addWidget(popup)

    assert popup.card.findings_box is not None
    texts = [label.text() for label in popup.card.findings_box.findChildren(QLabel)]
    assert "Shares what you do here with 4 other companies" in texts
    assert list(popup.buttons) == ["acknowledge"], (
        "a notice still asks nothing: its one button only says it has been read"
    )


def test_the_band_pulses_when_an_act_now_card_lands_and_then_rests(qtbot) -> None:
    urgent = InterventionPopup(decision("urgent"))
    calm = InterventionPopup(decision("calm", Outcome.INFORM).model_copy(update={"risk": 0.1}))
    qtbot.addWidget(urgent)
    qtbot.addWidget(calm)
    urgent.show()
    calm.show()

    assert urgent.card._pulse is not None and urgent.card._pulse.loopCount() == 3
    assert calm.card._pulse is None, "a green card has nothing to flash about"
    qtbot.waitUntil(
        lambda: urgent.card._pulse.state() != urgent.card._pulse.State.Running, timeout=5_000
    )
    assert urgent.card.band is not None and urgent.card.band.get_glow() == 0.0


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
