from __future__ import annotations

from collections import deque
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from privacy_guardian.core.events import Decision, Outcome
from privacy_guardian.engine.presentation import urgency_for
from privacy_guardian.ui import icons
from privacy_guardian.ui.card import (
    CARD_WIDTH,
    FLOATING_FLAGS,
    SCREEN_MARGIN,
    GuardianCard,
    anchor_bottom_right,
    make_floating,
    release_surface,
    scrollable,
    urgency_label,
)
from privacy_guardian.ui.theme import card_stylesheet, palette
from privacy_guardian.util.i18n import tr

# Closing a card must never act on the person's behalf. Where the safe default is a
# refusal it stands; where it would do something — open system settings, say — the
# close control only closes.
PROTECTIVE_DEFAULTS = frozenset({"cancel", "reject_optional", "block"})
# How many times the band pulses when a card of each tier arrives. Bounded, always:
# a light that never stops flashing is one people learn to stop seeing.
PULSES = {"act_now": 3, "attention": 1}


class InterventionPopup(QWidget):
    """The floating widget. Frameless, never steals focus until it is touched.

    It stays up until the person deals with it. A warning that removes itself after a
    few seconds is a warning they may never have finished reading, and one they cannot
    act on once it is gone.
    """

    action_selected = Signal(str, str, bool)
    closed = Signal()

    def __init__(
        self,
        decision: Decision,
        on_action: Any = None,
        parent: QWidget | None = None,
        mode: str = "system",
    ) -> None:
        super().__init__(parent, FLOATING_FLAGS)
        self.decision = decision
        self.mode = mode
        self._resolved = False
        make_floating(self)
        self.setAccessibleName(tr("app_name"))
        self.setAccessibleDescription(decision.explanation)
        self.setFixedWidth(CARD_WIDTH + 2 * SCREEN_MARGIN)
        self.setStyleSheet(card_stylesheet(mode))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = GuardianCard(mode, urgency=self.urgency())
        self.scroller = scrollable(self.card)
        outer.addWidget(self.scroller)
        self._pulsed = False
        self._build()
        self.buttons = self.card.buttons
        if on_action:
            self.action_selected.connect(on_action)
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: self.set_theme(self.mode)
        )

    # -- construction ---------------------------------------------------------

    def urgency(self) -> str:
        """The tier the card is shown in; computed here for decisions built by hand."""
        return self.decision.urgency or urgency_for(self.decision)

    def _band_label(self) -> str:
        return urgency_label(self.urgency(), handled=bool(self.decision.auto_action))

    def _build(self) -> None:
        decision = self.decision
        informational = decision.outcome == Outcome.INFORM
        card = self.card
        card.add_header(title=self._band_label(), right=tr("app_name"))
        card.closed.connect(self.dismiss)
        self.headline = card.add_headline(decision.title or decision.explanation)
        if informational:
            # A notice reports a fact: the band says how much it matters, the headline
            # says what, the rows say exactly which things, the context line says
            # where. Nothing on it needs deciding, so it is given no row of choices —
            # but it is given the one button there is to give, because a card whose
            # only control is a cross reads as a card still waiting for an answer, and
            # leaves the person hunting for the way to put it down.
            self.explanation = card.add_body(decision.detail) if decision.detail else self.headline
            if decision.findings:
                card.add_rows(decision.findings)
            self._add_rationale()
            # Hidden until "Why am I seeing this?" is opened, and a child of the card
            # from the start: a checkbox with no parent is a window of its own, and
            # showing it put a stray tick box in the middle of the screen.
            self.remember = QCheckBox(tr("remember"))
            self.remember.installEventFilter(self)
            self.remember.hide()
            card.add_widget(self.remember)
            card.add_context(decision.subject, decision.destination)
            acknowledge = card.add_acknowledgement(tr("acknowledge"), self.acknowledge)
            acknowledge.installEventFilter(self)
            card.add_footer(on_why=self.toggle_rationale if decision.rationale else None)
            if card.why_button is not None:
                card.why_button.installEventFilter(self)
            return
        blocks = ("rows", "body") if decision.layout == "findings_first" else ("body", "rows")
        self.explanation = self.headline
        for block in blocks:
            if block == "body" and decision.detail:
                self.explanation = card.add_body(decision.detail)
            elif block == "rows" and decision.findings:
                card.add_rows(decision.findings)
        self._add_rationale()
        # "Don't ask again" belongs with the reasoning, not in the way of the decision.
        self.remember = QCheckBox(tr("remember"))
        self.remember.installEventFilter(self)
        self.remember.hide()
        card.add_widget(self.remember)
        card.add_context(decision.subject, decision.destination)
        card.add_actions(
            decision.actions,
            decision.action_labels,
            decision.primary_action or decision.default_action,
            decision.tertiary_action,
            self.choose,
        )
        for button in card.buttons.values():
            button.installEventFilter(self)
        card.add_footer(on_why=self.toggle_rationale if decision.rationale else None)
        if self.card.why_button is not None:
            self.card.why_button.installEventFilter(self)

    def _add_rationale(self) -> None:
        self.rationale = QLabel("\n".join(f"\u00b7 {line}" for line in self.decision.rationale))
        self.rationale.setObjectName("cardBody")
        self.rationale.setWordWrap(True)
        self.rationale.hide()
        self.card.add_widget(self.rationale)

    # -- behaviour ------------------------------------------------------------

    def set_theme(self, mode: str) -> None:
        self.mode = mode
        self.setStyleSheet(card_stylesheet(mode))
        self.card.set_mode(mode)

    def toggle_rationale(self) -> None:
        showing = not self.rationale.isVisible()
        self.rationale.setVisible(showing and bool(self.decision.rationale))
        self.remember.setVisible(showing)
        self.reanchor()

    def reanchor(self) -> None:
        """Re-measure and re-pin: the card grows and shrinks as the user expands it."""
        anchor_bottom_right(self, self.scroller.widget())

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        # A word-wrapped label only reports its real height once it has been laid out
        # at its final width, so the first honest measurement is after the first show.
        QTimer.singleShot(0, self.reanchor)
        if not self._pulsed:
            # The band breathes when the card lands, and only then: three times for a
            # card that has stopped something, once for one that wants a decision.
            self._pulsed = True
            self.card.pulse(PULSES.get(self.urgency(), 0))

    def update_decision(self, decision: Decision) -> None:
        """Refinement arriving after the widget is up must not rewrite it underneath the user."""
        self.decision = decision
        self.headline.setText(decision.title or decision.explanation)
        if self.explanation is not self.headline:
            self.explanation.setText(decision.detail)
        self.rationale.setText("\n".join(f"· {line}" for line in decision.rationale))
        self.setAccessibleDescription(decision.explanation)
        if self.urgency() != self.card.urgency:
            self.card.set_urgency(self.urgency(), self._band_label())
        elif self.card.band_label is not None:
            self.card.band_label.setText(self._band_label())

    def choose(self, action: str) -> None:
        if self._resolved or action not in self.decision.actions:
            return
        self._resolved = True
        self.action_selected.emit(self.decision.event_id, action, self.remember.isChecked())
        self._close()

    def acknowledge(self) -> None:
        """The OK button on a notice: the close control, said out loud.

        A notice asks nothing, so reading it is the whole of the answer. Pressing OK
        and pressing the cross therefore have to mean the same thing, or the card
        would be offering two ways out that record different things.
        """
        self.dismiss()

    def dismiss_action(self) -> str:
        """What stepping away means, when it means anything at all."""
        default = self.decision.default_action
        if default in PROTECTIVE_DEFAULTS and default in self.decision.actions:
            return default
        return "continue" if "continue" in self.decision.actions else ""

    def dismiss(self, answered: bool = True) -> None:
        """The close control: step away, holding whatever the safe answer was.

        Stepping aside for another surface passes `answered=False`: whatever the card
        was holding still takes its protective default, but a notice the person never
        responded to is not recorded as one they dealt with, because they did not.
        """
        action = self.dismiss_action()
        if action and (answered or action in PROTECTIVE_DEFAULTS):
            self.choose(action)
            return
        self._resolved = True
        self._close()

    def _close(self) -> None:
        self.hide()
        release_surface(self)
        self.closed.emit()

    def eventFilter(self, watched: Any, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease:
            QTimer.singleShot(0, lambda: self._enable_focus(watched))
        return super().eventFilter(watched, event)

    def _enable_focus(self, watched: Any = None) -> None:
        if self._resolved or not self.isVisible():
            return
        if self.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus:
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
            self.show()
            self.activateWindow()
        if watched is not None:
            watched.setFocus()

    def mousePressEvent(self, event: Any) -> None:
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
        self.show()
        self.activateWindow()
        super().mousePressEvent(event)

    def stack_content(self) -> QWidget:
        return self.scroller.widget()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)


class PopupQueue(QWidget):
    """One widget at a time, bottom-right, newest decision for an event winning."""

    def __init__(self, service: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.queue: deque[Decision] = deque()
        self.current: InterventionPopup | None = None
        self.held = False
        self.anchor: Any = None
        self.reconcile_timer = QTimer(self)
        self.reconcile_timer.timeout.connect(self._reconcile)
        self.reconcile_timer.start(500)

    def enqueue(self, decision: Decision) -> None:
        if decision.outcome == Outcome.IGNORE:
            return
        if self.current and self.current.decision.event_id == decision.event_id:
            self.current.update_decision(decision)
            self.current.reanchor()
            return
        if any(item.event_id == decision.event_id for item in self.queue):
            self.queue = deque(
                decision if item.event_id == decision.event_id else item for item in self.queue
            )
            return
        self.queue.append(decision)
        self._next()

    def _next(self) -> None:
        if self.current or self.held or not self.queue:
            return
        decision = self.queue.popleft()
        core = getattr(self.service, "core", None)
        if core is not None and decision.event_id in core.actions:
            QTimer.singleShot(0, self._next)
            return
        self.current = InterventionPopup(decision, self._respond)
        self.current.closed.connect(self._closed)
        self.current.show()
        self.current.reanchor()

    def _reconcile(self) -> None:
        core = getattr(self.service, "core", None)
        if (
            self.current is not None
            and core is not None
            and self.current.decision.event_id in core.actions
        ):
            self.current.hide()
            release_surface(self.current)
            self._closed()

    def _respond(self, event_id: str, action: str, remember: bool) -> None:
        self.service.submit_response(event_id, action, remember)

    # -- making room ------------------------------------------------------------

    def dismiss_current(self) -> None:
        """Step away from the card that is up, exactly as its close control would.

        The thorough check is asked for on purpose and reports on everything the card
        was about, so the card gives way to it rather than sharing the corner. The safe
        answer stands for anything the card was holding, the same as closing it.
        """
        if self.current is not None:
            self.current.dismiss(answered=False)

    def hold(self) -> None:
        """Keep the cards that have not been shown yet until release() is called.

        They are not dropped: a warning the person has never seen is still owed to
        them, just not on top of the surface they asked for.
        """
        self.held = True

    def release(self) -> None:
        self.held = False
        self._next()

    def _closed(self) -> None:
        if self.current:
            release_surface(self.current)
            self.current.deleteLater()
            self.current = None
        QTimer.singleShot(0, self._next)


class ConfirmationBar(QWidget):
    """The compact 'x fields marked as not needed  [Done]' strip after an action lands."""

    done = Signal()

    def __init__(self, message: str, parent: QWidget | None = None, mode: str = "system") -> None:
        super().__init__(parent, FLOATING_FLAGS)
        make_floating(self)
        self.setStyleSheet(card_stylesheet(mode))
        colors = palette(mode)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN)
        card = GuardianCard(mode, self, urgency="all_clear")
        card.setFixedWidth(320)
        card.finish()
        row = QHBoxLayout()
        row.setSpacing(10)
        tick = QLabel()
        tick.setPixmap(icons.pixmap("ok", colors["ok"], 18))
        row.addWidget(tick)
        label = QLabel(message)
        label.setObjectName("cardRow")
        row.addWidget(label, 1)
        button = QPushButton(tr("done"))
        button.setProperty("tier", "primary")
        button.clicked.connect(self.dismiss)
        row.addWidget(button)
        card.add_layout(row)
        outer.addWidget(card)
        self.setAccessibleName(message)
        self._finished = False
        QTimer.singleShot(6000, self.dismiss)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, lambda: anchor_bottom_right(self))

    def dismiss(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.hide()
        release_surface(self)
        self.done.emit()
        self.deleteLater()
