"""Setup, as a walkthrough that checks its own work.

The browser extension is where most of Privacy Guardian's signal comes from, so setup
does not treat loading it as advice. It registers the native bridge first, shows exactly
where the extension lives, then waits until a browser really has connected before it
will move on. Skipping is possible, but it is a deliberate choice and it leaves setup
marked incomplete rather than pretending the app is ready.
"""

from __future__ import annotations

import sys
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from privacy_guardian.ui import icons
from privacy_guardian.ui.theme import palette, stylesheet
from privacy_guardian.util.i18n import tr

PAGES = ("local", "permissions", "extension", "cloud", "finish")


def _body(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("role", "body")
    return label


def _clear(layout: QVBoxLayout) -> None:
    """Empty a layout now, not on the next event loop turn."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            _clear_any(child)
            child.deleteLater()


def _clear_any(layout: Any) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        nested = item.layout()
        if nested is not None:
            _clear_any(nested)
            nested.deleteLater()


def _status_row(state: str, text: str, colors: dict[str, str]) -> QHBoxLayout:
    glyph = {"ok": "ok", "warn": "warn", "pending": "pending"}.get(state, "pending")
    tint = {"ok": colors["ok"], "warn": colors["warn"]}.get(state, colors["faint"])
    row = QHBoxLayout()
    row.setSpacing(8)
    icon = QLabel()
    icon.setPixmap(icons.pixmap(glyph, tint, 15))
    icon.setFixedWidth(19)
    icon.setAlignment(Qt.AlignmentFlag.AlignTop)
    row.addWidget(icon)
    label = QLabel(text)
    label.setWordWrap(True)
    row.addWidget(label, 1)
    return row


class StepPage(QWizardPage):
    """A page that can refresh itself while it is on screen."""

    def __init__(self, wizard: Onboarding, key: str) -> None:
        super().__init__()
        self.wizard_ref = wizard
        self.key = key
        self._shown: object = None
        self.setTitle(tr(key + "_title"))
        self.box = QVBoxLayout(self)
        self.box.setSpacing(10)
        self.box.addWidget(_body(tr(key + "_body")))

    def refresh(self) -> None:
        return None


class PermissionsPage(StepPage):
    """Optional desktop monitoring, with live status so the person can see it land."""

    def __init__(self, wizard: Onboarding) -> None:
        super().__init__(wizard, "permissions")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.box.addWidget(self.status)
        choices = (
            [("full_disk", "full_disk_access"), ("accessibility", "accessibility")]
            if sys.platform == "darwin"
            else [("full_disk", "app_permissions")]
        )
        for permission, label in choices:
            button = QPushButton(tr(label))
            button.clicked.connect(
                lambda _checked=False, value=permission: wizard.service.open_settings(value)
            )
            self.box.addWidget(button)
        self.box.addWidget(_body(tr("permissions_optional")))
        self.box.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        status = self.wizard_ref.service.permissions_status()
        if status == self._shown:
            return
        self._shown = dict(status)
        self.status.setText(
            "\n".join(
                ("✓ " if available else "○ ")
                + tr(name)
                + ": "
                + tr("available" if available else "unavailable")
                for name, available in status.items()
            )
        )


class ExtensionPage(StepPage):
    """The step that has to actually work before setup continues."""

    def __init__(self, wizard: Onboarding) -> None:
        super().__init__(wizard, "extension")
        colors = palette()
        self.registered = False
        self.skipped = False

        self.bridge_status = QLabel(tr("bridge_pending"))
        self.bridge_status.setWordWrap(True)
        self.box.addWidget(self.bridge_status)

        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setAccessibleName(tr("extension_folder"))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.path_field, 1)
        copy = QPushButton(tr("copy_path"))
        copy.clicked.connect(self._copy)
        row.addWidget(copy)
        reveal = QPushButton(tr("extension_install"))
        reveal.clicked.connect(wizard.service.open_extension_folder)
        row.addWidget(reveal)
        self.box.addLayout(row)
        self.box.addWidget(_body(tr("extension_steps")))

        self.connection = QWidget()
        self.connection_box = QVBoxLayout(self.connection)
        self.connection_box.setContentsMargins(0, 0, 0, 0)
        self.box.addWidget(self.connection)
        self.colors = colors

        skip_row = QHBoxLayout()
        skip_row.addStretch(1)
        self.skip = QPushButton(tr("continue_without_extension"))
        self.skip.setProperty("tier", "tertiary")
        self.skip.clicked.connect(self._confirm_skip)
        skip_row.addWidget(self.skip)
        self.box.addLayout(skip_row)
        self.box.addStretch(1)

    def initializePage(self) -> None:
        # Register the bridge before asking anyone to load the extension: without it the
        # extension has nothing to connect to, and setup would wait for something that
        # cannot happen.
        self.path_field.setText(str(self.wizard_ref.service.extension_folder()))
        self.path_field.setCursorPosition(0)
        registered, detail = self.wizard_ref.service.register_bridge()
        self.registered = registered
        self.bridge_status.setText(detail)
        self.refresh()

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.path_field.text())

    def _confirm_skip(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("app_name"),
            tr("skip_extension_warning"),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.skipped = True
            self.refresh()
            self.completeChanged.emit()

    @property
    def connected(self) -> list[str]:
        browsers: list[str] = list(self.wizard_ref.service.connected_browsers())
        return browsers

    def refresh(self) -> None:
        # Polled once a second, so only rebuild when something has actually changed.
        browsers = self.connected
        state_key = (tuple(browsers), self.skipped)
        if state_key == self._shown:
            return
        self._shown = state_key
        _clear(self.connection_box)
        if browsers:
            state, text = "ok", tr("extension_connected", browsers=", ".join(sorted(browsers)))
        elif self.skipped:
            state, text = "warn", tr("extension_skipped")
        else:
            state, text = "pending", tr("extension_waiting")
        self.connection_box.addLayout(_status_row(state, text, self.colors))
        self.skip.setVisible(not browsers)
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        """Next stays disabled until a browser has really connected, or skip is chosen."""
        return bool(self.connected) or self.skipped


class CloudPage(StepPage):
    def __init__(self, wizard: Onboarding) -> None:
        super().__init__(wizard, "cloud")
        self.box.addWidget(wizard.cloud_enabled)
        self.box.addWidget(wizard.key_input)
        self.box.addStretch(1)


class FinishPage(StepPage):
    """A summary of what is actually set up, not a claim that everything is."""

    def __init__(self, wizard: Onboarding) -> None:
        super().__init__(wizard, "finish")
        self.summary = QWidget()
        self.summary_box = QVBoxLayout(self.summary)
        self.summary_box.setContentsMargins(0, 0, 0, 0)
        self.summary_box.setSpacing(7)
        self.box.addWidget(self.summary)
        self.box.addWidget(wizard.autostart)
        self.box.addStretch(1)
        self.colors = palette()

    def initializePage(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        extension = self.wizard_ref.extension_page
        state_key = (
            extension.registered,
            tuple(extension.connected),
            tuple(sorted(self.wizard_ref.service.permissions_status().items())),
        )
        if state_key == self._shown:
            return
        self._shown = state_key
        _clear(self.summary_box)
        rows: list[tuple[str, str]] = [
            (
                "ok" if extension.registered else "warn",
                tr("summary_bridge_ok") if extension.registered else tr("summary_bridge_missing"),
            )
        ]
        browsers = extension.connected
        rows.append(
            ("ok", tr("extension_connected", browsers=", ".join(sorted(browsers))))
            if browsers
            else ("warn", tr("summary_extension_missing"))
        )
        granted = [
            name
            for name, available in self.wizard_ref.service.permissions_status().items()
            if available
        ]
        rows.append(
            ("ok", tr("summary_permissions_ok", names=", ".join(tr(name) for name in granted)))
            if granted
            else ("pending", tr("summary_permissions_none"))
        )
        for state, text in rows:
            self.summary_box.addLayout(_status_row(state, text, self.colors))


class Onboarding(QWizard):
    def __init__(self, service: Any) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle(tr("app_name"))
        self.setMinimumSize(560, 460)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setStyleSheet(stylesheet())
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.autostart = QCheckBox(tr("autostart"))
        self.autostart.setChecked(service.settings.autostart)
        self.cloud_enabled = QCheckBox(tr("llm_enable"))
        self.cloud_enabled.setChecked(service.settings.llm.enabled)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText(tr("api_key"))
        self.key_input.setAccessibleName(tr("api_key"))

        self.permissions_page = PermissionsPage(self)
        self.extension_page = ExtensionPage(self)
        self.pages: dict[str, StepPage] = {
            "local": StepPage(self, "local"),
            "permissions": self.permissions_page,
            "extension": self.extension_page,
            "cloud": CloudPage(self),
            "finish": FinishPage(self),
        }
        for key in PAGES:
            self.addPage(self.pages[key])
        # Kept for callers and tests that reach for the old attribute name.
        self.permission_status = self.permissions_page.status
        self.accepted.connect(self._finish)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(1000)
        self._refresh()

    def _refresh(self) -> None:
        current = self.currentPage()
        if isinstance(current, StepPage):
            current.refresh()
        elif isinstance(self.permission_status, QLabel):
            self.permissions_page.refresh()

    def present(self) -> None:
        from privacy_guardian.ui.card import bring_to_front

        bring_to_front(self)

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
        # Setup counts as done only when the part the product depends on is working.
        ready = bool(self.extension_page.connected) and self.extension_page.registered
        self.service.settings.onboarding_complete = ready
        self.service.settings.save()
        if not ready:
            QMessageBox.information(self, tr("app_name"), tr("setup_incomplete"))
