from __future__ import annotations

from collections import deque
from typing import Any, Literal

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from privacy_guardian.core.events import Decision, Outcome
from privacy_guardian.ui.card import CARD_WIDTH, SCREEN_MARGIN, GuardianCard, glyph
from privacy_guardian.ui.theme import card_stylesheet, palette
from privacy_guardian.util.i18n import tr

INFORM_MILLISECONDS = 8000
INTERVENE_MILLISECONDS = 60000


class InterventionPopup(QWidget):
    """The floating widget. Frameless, never steals focus until it is touched."""

    action_selected = Signal(str, str, bool)
    closed = Signal()

    def __init__(
        self,
        decision: Decision,
        on_action: Any = None,
        parent: QWidget | None = None,
        mode: str = "system",
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.decision = decision
        self.mode = mode
        self._resolved = False
        self._remaining = (
            INFORM_MILLISECONDS if decision.outcome == Outcome.INFORM else INTERVENE_MILLISECONDS
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName(tr("app_name"))
        self.setAccessibleDescription(decision.explanation)
        self.setFixedWidth(CARD_WIDTH + 2 * SCREEN_MARGIN)
        self.setStyleSheet(card_stylesheet(mode))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN)
        self.card = GuardianCard(mode, self)
        outer.addWidget(self.card)
        self._build()
        self.buttons = self.card.buttons
        if on_action:
            self.action_selected.connect(on_action)
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: self.set_theme(self.mode)
        )
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)
        self.timer.start(self._remaining)
        if self.card.progress is not None:
            self.countdown = QTimer(self)
            self.countdown.timeout.connect(self._tick)
            self.countdown.start(100)

    # -- construction ---------------------------------------------------------

    def _build(self) -> None:
        decision = self.decision
        informational = decision.outcome == Outcome.INFORM
        card = self.card
        if informational:
            # A toast reports a fact: a status glyph, a line, and a countdown. No buttons.
            self.headline = self._status_row()
            self.explanation = card.add_body(decision.detail or decision.explanation)
            self._add_rationale()
            self.remember = QCheckBox(tr("remember"))
            self.remember.hide()
            card.add_footer()
            card.add_countdown(INFORM_MILLISECONDS)
            return
        card.add_header(right=self._origin())
        card.closed.connect(self.dismiss)
        self.headline = card.add_headline(decision.title or decision.explanation)
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

    def _status_row(self) -> QLabel:
        severity: Literal["warn", "ok", "info"] = (
            "warn"
            if any(finding.severity == "warn" for finding in self.decision.findings)
            else "ok"
        )
        label = QLabel(self.decision.title or self.decision.explanation)
        label.setObjectName("cardHeadline")
        label.setWordWrap(True)
        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(glyph(severity, self.card.colors["ok" if severity == "ok" else "warn"]))
        row.addWidget(label, 1)
        self.card.add_layout(row)
        return label

    def _origin(self) -> str:
        return self.decision.destination if self.decision.subject else ""

    # -- behaviour ------------------------------------------------------------

    def set_theme(self, mode: str) -> None:
        self.mode = mode
        self.setStyleSheet(card_stylesheet(mode))
        self.card.colors = palette(mode)
        self.card.setStyleSheet(card_stylesheet(mode))

    def toggle_rationale(self) -> None:
        showing = not self.rationale.isVisible()
        self.rationale.setVisible(showing and bool(self.decision.rationale))
        self.remember.setVisible(showing)
        self.adjustSize()

    def update_decision(self, decision: Decision) -> None:
        """Refinement arriving after the widget is up must not rewrite it underneath the user."""
        self.decision = decision
        self.headline.setText(decision.title or decision.explanation)
        if self.explanation is not self.headline:
            self.explanation.setText(decision.detail)
        self.rationale.setText("\n".join(f"· {line}" for line in decision.rationale))
        self.setAccessibleDescription(decision.explanation)

    def choose(self, action: str) -> None:
        if self._resolved or action not in self.decision.actions:
            return
        self._resolved = True
        self.timer.stop()
        self.action_selected.emit(self.decision.event_id, action, self.remember.isChecked())
        self.hide()
        self.closed.emit()

    def dismiss(self) -> None:
        """The close control: step away without choosing, exactly like letting it time out."""
        self.timeout()

    def timeout(self) -> None:
        if self.decision.outcome == Outcome.INTERVENE:
            self.choose(self.decision.default_action)
        else:
            self._resolved = True
            self.timer.stop()
            self.hide()
            self.closed.emit()

    def _tick(self) -> None:
        if self.card.progress is None:
            return
        self._remaining = max(0, self._remaining - 100)
        self.card.progress.setValue(self._remaining)

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

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.timeout()
        else:
            super().keyPressEvent(event)


class PopupQueue(QWidget):
    """One widget at a time, bottom-right, newest decision for an event winning."""

    def __init__(self, service: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.queue: deque[Decision] = deque()
        self.current: InterventionPopup | None = None
        self.anchor: Any = None
        self.reconcile_timer = QTimer(self)
        self.reconcile_timer.timeout.connect(self._reconcile)
        self.reconcile_timer.start(500)

    def enqueue(self, decision: Decision) -> None:
        if decision.outcome == Outcome.IGNORE:
            return
        if self.current and self.current.decision.event_id == decision.event_id:
            self.current.update_decision(decision)
            return
        if any(item.event_id == decision.event_id for item in self.queue):
            self.queue = deque(
                decision if item.event_id == decision.event_id else item for item in self.queue
            )
            return
        self.queue.append(decision)
        self._next()

    def _next(self) -> None:
        if self.current or not self.queue:
            return
        decision = self.queue.popleft()
        core = getattr(self.service, "core", None)
        if core is not None and decision.event_id in core.actions:
            QTimer.singleShot(0, self._next)
            return
        self.current = InterventionPopup(decision, self._respond)
        self.current.closed.connect(self._closed)
        self.current.adjustSize()
        screen = QGuiApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            self.current.move(
                rect.right() - self.current.width() + 1,
                rect.bottom() - self.current.height() + 1,
            )
        self.current.show()

    def _reconcile(self) -> None:
        core = getattr(self.service, "core", None)
        if (
            self.current is not None
            and core is not None
            and self.current.decision.event_id in core.actions
        ):
            self.current.hide()
            self._closed()

    def _respond(self, event_id: str, action: str, remember: bool) -> None:
        self.service.submit_response(event_id, action, remember)

    def _closed(self) -> None:
        if self.current:
            self.current.deleteLater()
            self.current = None
        QTimer.singleShot(0, self._next)


class ConfirmationBar(QWidget):
    """The compact 'x fields marked as not needed  [Done]' strip after an action lands."""

    done = Signal()

    def __init__(self, message: str, parent: QWidget | None = None, mode: str = "system") -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        from privacy_guardian.ui import icons

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(card_stylesheet(mode))
        colors = palette(mode)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN)
        card = GuardianCard(mode, self)
        card.setFixedWidth(320)
        card.finish()
        row = QHBoxLayout()
        row.setSpacing(10)
        lock = QLabel()
        lock.setPixmap(icons.pixmap("padlock", colors["accent"], 16))
        row.addWidget(lock)
        label = QLabel(message)
        label.setObjectName("cardRow")
        row.addWidget(label, 1)
        button = QPushButton(tr("done"))
        button.setProperty("tier", "primary")
        button.clicked.connect(self._finish)
        row.addWidget(button)
        card.add_layout(row)
        outer.addWidget(card)
        self.setAccessibleName(message)
        QTimer.singleShot(6000, self._finish)

    def _finish(self) -> None:
        self.hide()
        self.done.emit()
        self.deleteLater()
