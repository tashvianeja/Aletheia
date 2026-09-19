from __future__ import annotations

from typing import Any

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from privacy_guardian.ui.icons import GLYPHS
from privacy_guardian.util.i18n import tr

# The menu bar shows a padlock with a small status dot beside it, as in the reference renders.
DOTS = {"idle": "#16a34a", "attention": "#d97706", "paused": "#9ca3af"}


def shield_icon(state: str = "idle", template: bool = True) -> QIcon:
    """A monochrome padlock plus a coloured status dot.

    The padlock is drawn in black and marked as a template image so macOS tints it for the
    light or dark menu bar; only the dot keeps its own colour.
    """
    dot = DOTS.get(state, DOTS["idle"])
    body = GLYPHS["padlock"].replace("{c}", "#000000")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 26 20">'
        f"{body}"
        f'<circle cx="22" cy="14.5" r="3.1" fill="{dot}"/>'
        "</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for height in (16, 18, 20, 22, 32, 44):
        width = round(height * 26 / 20)
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()
        icon.addPixmap(pixmap)
    icon.setIsMask(template)
    return icon


class GuardianTray(QSystemTrayIcon):
    """The one always-visible surface: a status line and the few things worth doing."""

    def __init__(self, service: Any, window_factory: Any = None) -> None:
        super().__init__(shield_icon())
        self.service = service
        self.window_factory = window_factory
        self.state = "idle"
        self.setToolTip(tr("app_name"))
        self.menu = QMenu()
        self.actions: dict[str, QAction] = {}
        self.status = self.menu.addAction(tr("watching_quietly"))
        self.status.setEnabled(False)
        self.menu.addSeparator()
        groups: list[list[tuple[str, Any]]] = [
            [
                ("deep_check", lambda: service.deep_check()),
                ("dashboard", lambda: service.show_dashboard()),
            ],
            [
                ("pause_hour", lambda: service.pause(3600)),
                ("pause_tomorrow", lambda: service.pause(86400)),
                ("resume", lambda: service.pause(0)),
            ],
            [
                ("preferences", lambda: service.show_dashboard("preferences")),
                ("recent", lambda: service.show_dashboard("events")),
                ("permissions", lambda: service.show_permissions()),
                ("extensions", lambda: service.show_extensions()),
                ("onboarding", lambda: service.show_onboarding()),
                ("updates", lambda: service.check_updates()),
            ],
            [("quit", lambda: service.quit())],
        ]
        for index, group in enumerate(groups):
            if index:
                self.menu.addSeparator()
            for key, callback in group:
                action = self.menu.addAction(tr(key))
                action.triggered.connect(callback)
                self.actions[key] = action
        self.actions["deep_check"].setShortcut(getattr(service.settings, "hotkey", "") or "")
        self.menu.setDefaultAction(self.actions["deep_check"])
        self.actions["resume"].setVisible(False)
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        self.show()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.service.deep_check()

    def set_state(self, state: str, pending: int = 0, resumes: str = "") -> None:
        """Drive the dot colour and the status line from what is actually outstanding."""
        self.state = state
        self.setIcon(shield_icon(state))
        if state == "paused":
            self.status.setText(tr("watching_paused", when=resumes or tr("unknown").lower()))
        elif state == "attention" and pending:
            key = "watching_attention" if pending == 1 else "watching_attention_plural"
            self.status.setText(tr(key, count=pending))
        else:
            self.status.setText(tr("watching_quietly"))
        self.actions["resume"].setVisible(state == "paused")
        self.actions["pause_hour"].setVisible(state != "paused")
        self.actions["pause_tomorrow"].setVisible(state != "paused")
        self.setToolTip(f"{tr('app_name')} — {self.status.text()}")
