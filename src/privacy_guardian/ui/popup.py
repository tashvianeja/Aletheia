from __future__ import annotations

from collections import deque
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from privacy_guardian.core.events import Decision, Outcome
from privacy_guardian.ui.theme import stylesheet
from privacy_guardian.util.i18n import tr


class InterventionPopup(QWidget):
    action_selected = Signal(str, str, bool)
    closed = Signal()

    def __init__(
        self, decision: Decision, on_action: Any = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.decision = decision
        self._resolved = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMaximumWidth(380)
        self.setMinimumWidth(350)
        self.setAccessibleName(tr("app_name"))
        self.setStyleSheet(stylesheet())
        layout = QVBoxLayout(self)
        title = QLabel(tr("app_name"))
        title.setStyleSheet("font-weight: 700; font-size: 15px")
        layout.addWidget(title)
        self.explanation = QLabel(decision.explanation)
        explanation = self.explanation
        explanation.setWordWrap(True)
        explanation.setAccessibleName(decision.explanation)
        layout.addWidget(explanation)
        document_summary = [line for line in decision.rationale if line.startswith(("⚠", "✓"))]
        if document_summary:
            summary = QLabel("\n".join(document_summary))
            summary.setWordWrap(True)
            layout.addWidget(summary)
        self.why_button = QPushButton(tr("why"))
        self.why_button.setCheckable(True)
        self.why_button.installEventFilter(self)
        self.rationale = QLabel("\n".join(decision.rationale))
        self.rationale.setWordWrap(True)
        self.rationale.hide()
        self.why_button.toggled.connect(self.rationale.setVisible)
        layout.addWidget(self.why_button)
        layout.addWidget(self.rationale)
        self.remember = QCheckBox(tr("remember"))
        self.remember.installEventFilter(self)
        layout.addWidget(self.remember)
        self.buttons: dict[str, QPushButton] = {}
        for start in range(0, len(decision.actions), 2):
            row = QHBoxLayout()
            for action in decision.actions[start : start + 2]:
                button = QPushButton(tr(action))
                button.setAccessibleName(tr(action))
                button.installEventFilter(self)
                button.clicked.connect(lambda _checked=False, value=action: self.choose(value))
                row.addWidget(button)
                self.buttons[action] = button
            layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)
        self.timer.start(8000 if decision.outcome == Outcome.INFORM else 60000)
        if on_action:
            self.action_selected.connect(on_action)
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: self.set_theme("system")
        )

    def set_theme(self, mode: str) -> None:
        self.setStyleSheet(stylesheet(mode))

    def choose(self, action: str) -> None:
        if self._resolved or action not in self.decision.actions:
            return
        self._resolved = True
        self.timer.stop()
        self.action_selected.emit(self.decision.event_id, action, self.remember.isChecked())
        self.hide()
        self.closed.emit()

    def timeout(self) -> None:
        if self.decision.outcome == Outcome.INTERVENE:
            self.choose(self.decision.default_action)
        else:
            self._resolved = True
            self.hide()
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

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.timeout()
        else:
            super().keyPressEvent(event)


class PopupQueue(QWidget):
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
            self.current.decision = decision
            self.current.explanation.setText(decision.explanation)
            self.current.rationale.setText("\n".join(decision.rationale))
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
            if self.anchor and not self.anchor.isNull():
                self.current.move(
                    min(self.anchor.x(), rect.right() - 380),
                    self.anchor.bottom() + 5
                    if self.anchor.y() < rect.center().y()
                    else self.anchor.top() - self.current.height() - 5,
                )
            else:
                self.current.move(rect.right() - 390, rect.top() + 20)
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
