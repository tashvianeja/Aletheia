from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton, QVBoxLayout, QWidget

from privacy_guardian.ui.theme import stylesheet
from privacy_guardian.util.i18n import tr


class DeepCheckWindow(QWidget):
    def __init__(self, service: Any) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle(tr("deep_check"))
        self.setMinimumSize(560, 460)
        self.setStyleSheet(stylesheet())
        layout = QVBoxLayout(self)
        self.status = QLabel(tr("checking"))
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.results = QListWidget()
        self.results.setAccessibleName(tr("details"))
        details = QPushButton(tr("details"))
        details.clicked.connect(lambda: service.show_dashboard())
        for widget in (self.status, self.progress, self.results, details):
            layout.addWidget(widget)

    def show_report(self, report: dict[str, Any]) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status.setText(str(report.get("summary", tr("check_complete"))))
        self.results.clear()
        for finding in report.get("findings", []):
            self.results.addItem("⚠ " + finding["summary"])
        for section in report.get("checked", []):
            mark = (
                "✓"
                if section.get("clean") and section.get("available")
                else "○"
                if not section.get("available")
                else "!"
            )
            self.results.addItem(
                f"{mark} {tr(section['kind'])}: {tr('checked_clean') if section.get('available') and section.get('clean') else tr('not_observed') if not section.get('available') else tr('details')}"
            )
        if not report.get("context_available"):
            self.results.addItem(tr("no_context"))
