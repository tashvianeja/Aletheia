from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon

from aletheia.util.i18n import tr


class Notifications:
    def __init__(self, tray: QSystemTrayIcon) -> None:
        self.tray = tray

    def inform(self, message: str) -> None:
        self.tray.showMessage(
            tr("app_name"), message, QSystemTrayIcon.MessageIcon.Information, 8000
        )
