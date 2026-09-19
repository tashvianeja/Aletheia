"""Every floating surface has to sit fully inside the usable screen area.

On macOS the Dock draws above an always-on-top tool window, so a widget positioned even
slightly too low is both clipped by the screen edge and hidden behind the Dock. The bug
these cover was measuring the window before its word-wrapped labels had been laid out,
which reported a height far smaller than the real one.
"""

from __future__ import annotations

import sys

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QScrollBar

from privacy_guardian.core.events import (
    ClipboardReadEvent,
    DataCategory,
    Decision,
    DecisionFinding,
    FileUploadEvent,
    Outcome,
    Requester,
)
from privacy_guardian.engine.decision import decide
from privacy_guardian.ui.deepcheck import DeepCheckWindow
from privacy_guardian.ui.popup import ConfirmationBar, InterventionPopup, PopupQueue


def available():
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    return screen.availableGeometry()


def assert_on_screen(widget) -> None:
    rect = available()
    frame = widget.frameGeometry()
    assert rect.contains(frame), (
        f"{type(widget).__name__} at {frame} is outside the usable area {rect}"
    )


def settle(qtbot, widget) -> None:
    """Show the surface and wait for it to place itself, as it does in the app."""
    widget.show()
    qtbot.waitUntil(lambda: widget.frameGeometry().bottom() == available().bottom(), timeout=2000)


def settle_above(qtbot, widget, below) -> None:
    """Show a surface and wait for it to take its place above the one already there.

    Waiting on "somewhere above the bottom edge" would pass before placement had run
    at all, because an unplaced window starts in the middle of the screen.
    """
    widget.show()
    qtbot.waitUntil(
        lambda: (
            widget.frameGeometry().right() == below.frameGeometry().right()
            and widget.frameGeometry().bottom() == below.frameGeometry().top() - 1
        ),
        timeout=2000,
    )


def upload_decision() -> Decision:
    event = FileUploadEvent(
        filename="passport.pdf",
        requester=Requester(
            origin="https://shrinkpix.example",
            display_name="shrinkpix.example",
            purpose="image_tool",
            purpose_confidence=0.9,
        ),
        data_categories=[
            DataCategory.GOVERNMENT_ID_PASSPORT,
            DataCategory.FULL_NAME,
            DataCategory.DOB,
            DataCategory.BIOMETRIC_PHOTO,
        ],
    )
    return decide(event)


def test_intervention_widget_sits_inside_the_usable_area(qtbot) -> None:
    popup = InterventionPopup(upload_decision())
    qtbot.addWidget(popup)

    settle(qtbot, popup)

    assert_on_screen(popup)
    rect = available()
    # Pinned to the bottom-right corner, as every reference render is.
    assert popup.frameGeometry().right() == rect.right()
    assert popup.frameGeometry().bottom() == rect.bottom()


def test_widget_is_measured_after_its_labels_have_wrapped(qtbot) -> None:
    """The height used for placement must be the laid-out height, not the pre-show guess."""
    popup = InterventionPopup(upload_decision())
    qtbot.addWidget(popup)
    guess = popup.sizeHint().height()

    settle(qtbot, popup)
    settled = popup.height()

    assert settled > guess, (
        "word-wrapped labels should report a taller height once laid out; "
        "if this stops being true the regression it guards has moved"
    )
    assert popup.frameGeometry().bottom() == available().bottom()


@pytest.mark.skipif(sys.platform != "darwin", reason="Dock layering is macOS-specific")
def test_widget_floats_above_the_dock(qtbot) -> None:
    """Qt's always-on-top sits below the Dock, which would hide a bottom-anchored widget."""
    objc = pytest.importorskip("objc")
    appkit = pytest.importorskip("AppKit")
    popup = InterventionPopup(upload_decision())
    qtbot.addWidget(popup)
    settle(qtbot, popup)

    window = objc.objc_object(c_void_p=int(popup.winId())).window()
    if window is None:
        pytest.skip("no native window under this platform plugin")
    assert window.level() >= appkit.NSStatusWindowLevel
    assert window.level() > 20, "must be above NSDockWindowLevel"


def test_widget_is_remeasured_after_expanding_the_reasoning(qtbot) -> None:
    popup = InterventionPopup(upload_decision())
    qtbot.addWidget(popup)
    settle(qtbot, popup)
    before = popup.height()

    popup.toggle_rationale()

    assert popup.height() > before, "expanding the reasoning should make the widget taller"
    assert_on_screen(popup)


def test_a_widget_taller_than_the_screen_is_capped_and_scrolls(qtbot) -> None:
    rect = available()
    crowded = upload_decision().model_copy(
        update={
            "findings": [
                DecisionFinding(
                    label=f"Finding {index} with a label long enough to wrap onto a second line",
                    severity="warn",
                    detail="And an explanatory sentence underneath it as well.",
                )
                for index in range(60)
            ]
        }
    )
    popup = InterventionPopup(crowded)
    qtbot.addWidget(popup)

    settle(qtbot, popup)

    assert_on_screen(popup)
    assert popup.height() <= rect.height()
    scrollbars = popup.findChildren(QScrollBar)
    assert any(bar.maximum() > 0 for bar in scrollbars), (
        "a card taller than the screen must scroll, or its buttons cannot be reached"
    )


def test_inform_toast_and_confirmation_bar_sit_inside_the_usable_area(qtbot) -> None:
    toast = InterventionPopup(upload_decision().model_copy(update={"outcome": Outcome.INFORM}))
    qtbot.addWidget(toast)
    settle(qtbot, toast)
    assert_on_screen(toast)

    bar = ConfirmationBar("3 fields marked as not needed")
    qtbot.addWidget(bar)
    settle_above(qtbot, bar, toast)
    assert_on_screen(bar)


def test_a_second_surface_stacks_above_the_first_instead_of_covering_it(
    qtbot, ui_controller
) -> None:
    """The bug this guards: a toast landing on the check card hid the buttons under it."""
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)
    settle(qtbot, window)
    settled = window.frameGeometry()

    toast = InterventionPopup(upload_decision().model_copy(update={"outcome": Outcome.INFORM}))
    qtbot.addWidget(toast)
    settle_above(qtbot, toast, window)

    assert not window.frameGeometry().intersects(toast.frameGeometry()), (
        "the newer surface must sit above the older one, not on top of it"
    )
    assert window.frameGeometry() == settled, "the card underneath must not be moved"
    assert_on_screen(window)
    assert_on_screen(toast)

    # Closing the one underneath brings the one above back down to the corner.
    window.close()
    qtbot.waitUntil(lambda: toast.frameGeometry().bottom() == available().bottom())


def test_deep_check_window_sits_inside_the_usable_area(qtbot, ui_controller) -> None:
    window = DeepCheckWindow(ui_controller)
    qtbot.addWidget(window)

    settle(qtbot, window)

    assert_on_screen(window)

    window.show_report(
        {
            "summary": "Overall: 2 things to review",
            "origin": "dropcrate.example",
            "findings": [
                {"summary": f"Finding {index}", "detail": "A sentence of explanation."}
                for index in range(4)
            ],
            "groups": [],
            "context_available": True,
        }
    )
    assert_on_screen(window)


def test_queue_shows_each_widget_on_screen(qtbot, ui_controller) -> None:
    queue = PopupQueue(ui_controller)
    qtbot.addWidget(queue)
    clipboard = decide(
        ClipboardReadEvent(
            requester=Requester(
                kind="application",
                bundle_id="com.snippetly",
                display_name="Snippetly",
                purpose="productivity",
                purpose_confidence=0.8,
            ),
            data_categories=[DataCategory.CREDENTIALS_PASSWORD],
            writer_key="other",
        )
    )

    queue.enqueue(clipboard)

    assert queue.current is not None
    qtbot.waitUntil(lambda: queue.current.frameGeometry().bottom() == available().bottom())
    assert_on_screen(queue.current)
