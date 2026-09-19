"""The thorough check, shown as the same floating card as every other intervention.

While it runs the card is a live checklist; when it finishes it becomes a result summary
with a way through to the full report in the dashboard.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from privacy_guardian.core.events import DecisionFinding
from privacy_guardian.ui import icons
from privacy_guardian.ui.card import CARD_WIDTH, SCREEN_MARGIN, GuardianCard
from privacy_guardian.ui.theme import card_stylesheet, palette
from privacy_guardian.util.i18n import tr

# The four lines the card ticks off while the check runs.
STAGES = (
    ("permissions", "Permissions"),
    ("tracking", "Tracking"),
    ("policy", "Privacy policy"),
    ("forms", "Current form"),
)
STAGE_SOURCES = {
    "permissions": {"permissions"},
    "tracking": {"tracking", "consent"},
    "policy": {"policy", "terms"},
    "forms": {"forms", "uploads"},
}


class DeepCheckWindow(QWidget):
    def __init__(self, service: Any, mode: str = "system") -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.service = service
        self.mode = mode
        self.colors = palette(mode)
        self.report: dict[str, Any] | None = None
        self.setWindowTitle(tr("deep_check"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(card_stylesheet(mode))
        self.setFixedWidth(CARD_WIDTH + 2 * SCREEN_MARGIN)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN)
        self.card: GuardianCard | None = None
        self.stage_glyphs: dict[str, QLabel] = {}
        self._show_running()

    # -- states ---------------------------------------------------------------

    def _reset_card(self) -> GuardianCard:
        if self.card is not None:
            self._outer.removeWidget(self.card)
            self.card.deleteLater()
        self.card = GuardianCard(self.mode, self)
        self.card.closed.connect(self.close)
        self._outer.addWidget(self.card)
        return self.card

    def _show_running(self) -> None:
        card = self._reset_card()
        card.add_header(title=tr("privacy_check"), right=self._origin())
        self.stage_glyphs = {}
        box = QVBoxLayout()
        box.setSpacing(7)
        for key, title in STAGES:
            row = QHBoxLayout()
            row.setSpacing(9)
            glyph = QLabel()
            glyph.setPixmap(icons.pixmap("pending", self.colors["faint"], 15))
            glyph.setFixedWidth(19)
            row.addWidget(glyph)
            row.addWidget(QLabel(title), 1)
            box.addLayout(row)
            self.stage_glyphs[key] = glyph
        card.add_layout(box)
        card.add_footer()
        self.status = card.headline_label or QLabel()
        self.adjustSize()
        self._anchor()

    def show_progress(self, update: dict[str, str] | str) -> None:
        """Tick a line as each part of the check reports in."""
        if isinstance(update, str) or self.card is None:
            return
        stage = update.get("stage", "")
        state = update.get("state", "")
        for key, sources in STAGE_SOURCES.items():
            if stage in sources and key in self.stage_glyphs:
                name, color = (
                    ("ok", self.colors["ok"])
                    if state == "done"
                    else ("pending", self.colors["faint"])
                )
                self.stage_glyphs[key].setPixmap(icons.pixmap(name, color, 15))

    def show_report(self, report: dict[str, Any]) -> None:
        self.report = report
        card = self._reset_card()
        card.add_header(title=tr("privacy_check"), right=self._origin(report))
        card.add_headline(str(report.get("summary", tr("check_complete"))))
        rows: list[DecisionFinding] = []
        for finding in report.get("findings", [])[:4]:
            rows.append(
                DecisionFinding(
                    label=str(finding.get("summary", "")),
                    severity="warn",
                    detail=str(finding.get("detail", "")),
                )
            )
        for group in report.get("groups", []):
            for entry in group.get("rows", []):
                if entry.get("severity") == "ok":
                    rows.append(DecisionFinding(label=str(entry.get("summary", "")), severity="ok"))
        if not report.get("context_available"):
            rows.append(DecisionFinding(label=tr("no_context"), severity="info"))
        card.add_rows(rows)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        done = QPushButton(tr("done"))
        done.clicked.connect(self.close)
        actions.addWidget(done)
        full = QPushButton(tr("details"))
        full.setProperty("tier", "primary")
        full.clicked.connect(self._open_full)
        actions.addWidget(full)
        card.add_layout(actions)
        card.add_footer()
        # Keep the attribute the older report tests and screenshot tooling reach for.
        self.status = card.headline_label or QLabel()
        self.adjustSize()
        self._anchor()

    def _open_full(self) -> None:
        if self.report is not None:
            self.service.show_report_window(self.report)
        else:
            self.service.show_dashboard("sites_and_apps")
        self.close()

    # -- placement -------------------------------------------------------------

    def _origin(self, report: dict[str, Any] | None = None) -> str:
        if report is not None:
            return str(report.get("origin", ""))
        core = getattr(self.service, "core", None)
        return str(getattr(core, "focused_origin", "") or "")

    def _anchor(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            self.move(rect.right() - self.width() + 1, rect.bottom() - self.height() + 1)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._anchor)
