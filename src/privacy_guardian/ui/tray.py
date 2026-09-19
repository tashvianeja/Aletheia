from __future__ import annotations

from typing import Any

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from privacy_guardian.util.i18n import tr


def shield_icon(state: str = "idle") -> QIcon:
    color = {"idle": "#7b8794", "attention": "#d38400", "paused": "#adb5bd"}.get(state, "#7b8794")
    dot = '<circle cx="25" cy="7" r="5" fill="#dc3545"/>' if state == "attention" else ""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path fill="{color}" d="M16 2 29 7v9c0 7-8 12-13 15C11 28 3 23 3 16V7z"/><path stroke="white" stroke-width="2" fill="none" d="m9 16 5 5 9-11"/>{dot}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        from PySide6.QtCore import Qt

        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class GuardianTray(QSystemTrayIcon):
    def __init__(self, service: Any, window_factory: Any = None) -> None:
        super().__init__(shield_icon())
        self.service = service
        self.window_factory = window_factory
        self.setToolTip(tr("app_name"))
        self.menu = QMenu()
        self.actions: dict[str, QAction] = {}
        entries = [
            ("deep_check", lambda: service.deep_check()),
            ("pause_hour", lambda: service.pause(3600)),
            ("pause_tomorrow", lambda: service.pause(86400)),
            ("resume", lambda: service.pause(0)),
            ("recent", lambda: service.show_dashboard()),
            ("dashboard", lambda: service.show_dashboard()),
            ("preferences", lambda: service.show_dashboard("preferences")),
            ("permissions", lambda: service.show_permissions()),
            ("extensions", lambda: service.show_extensions()),
            ("onboarding", lambda: service.show_onboarding()),
            ("updates", lambda: service.check_updates()),
            ("quit", lambda: service.quit()),
        ]
        for key, callback in entries:
            action = self.menu.addAction(tr(key))
            action.triggered.connect(callback)
            self.actions[key] = action
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        self.show()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.service.deep_check()

    def set_state(self, state: str) -> None:
        self.setIcon(shield_icon(state))
