from __future__ import annotations

import sys
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from privacy_guardian.util.i18n import tr


class Onboarding(QWizard):
    def __init__(self, service: Any) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle(tr("app_name"))
        self.setMinimumSize(520, 360)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.permission_status: QLabel | None = None
        self.autostart = QCheckBox(tr("autostart"))
        self.autostart.setChecked(service.settings.autostart)
        self.cloud_enabled = QCheckBox(tr("llm_enable"))
        self.cloud_enabled.setChecked(service.settings.llm.enabled)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setAccessibleName(tr("api_key"))
        for key in ("local", "permissions", "extension", "cloud", "finish"):
            page = QWizardPage()
            page.setTitle(tr(key + "_title"))
            layout = QVBoxLayout(page)
            body = QLabel(tr(key + "_body"))
            body.setWordWrap(True)
            layout.addWidget(body)
            if key == "permissions":
                self.permission_status = QLabel()
                layout.addWidget(self.permission_status)
                choices = (
                    [("full_disk", "full_disk_access"), ("accessibility", "accessibility")]
                    if sys.platform == "darwin"
                    else [("full_disk", "app_permissions")]
                )
                for permission, label in choices:
                    button = QPushButton(tr(label))
                    button.clicked.connect(
                        lambda _checked=False, permission=permission: service.open_settings(
                            permission
                        )
                    )
                    layout.addWidget(button)
            elif key == "extension":
                button = QPushButton(tr("extension_install"))
                button.clicked.connect(service.open_extension_folder)
                layout.addWidget(button)
            elif key == "cloud":
                layout.addWidget(self.cloud_enabled)
                layout.addWidget(self.key_input)
            if key == "finish":
                layout.addWidget(self.autostart)
            self.addPage(page)
        self.accepted.connect(self._finish)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(1000)
        self._refresh()

    def _refresh(self) -> None:
        if self.permission_status:
            status = self.service.permissions_status()
            self.permission_status.setText(
                "\n".join(
                    ("✓ " if available else "○ ")
                    + tr(name)
                    + ": "
                    + tr("available" if available else "unavailable")
                    for name, available in status.items()
                )
            )

    def _finish(self) -> None:
        self.service.settings.llm.enabled = self.cloud_enabled.isChecked()
        if self.key_input.text():
            from privacy_guardian.llm.client import set_api_key

            try:
                set_api_key(self.key_input.text())
                self.key_input.clear()
            except Exception:
                QMessageBox.warning(self, tr("app_name"), tr("settings_failed"))
                return
        self.service.settings.autostart = self.autostart.isChecked()
        from privacy_guardian.util.installation import install

        install(self.service.settings)
        self.service.settings.onboarding_complete = True
        self.service.settings.save()
