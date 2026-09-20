"""The thorough check, shown as the same floating card as every other intervention.

While it runs the card is a live checklist; when it finishes it becomes a result summary
with a way through to the full report in the dashboard.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from privacy_guardian.core.events import DecisionFinding
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
)
from privacy_guardian.ui.theme import card_stylesheet, palette, urgency_palette
from privacy_guardian.util.i18n import tr

# The four lines the card ticks off while the check runs.
STAGES = (
    ("permissions", "Permissions"),
    ("tracking", "Tracking"),
    ("policy", "Privacy policy"),
    ("forms", "Current form"),
)
# As many findings as fit on a card that can still be read at a glance; the rest are
# one line away in the full report.
MAX_ROWS = 5
STAGE_SOURCES = {
    "permissions": {"permissions"},
    "tracking": {"tracking", "consent"},
    "policy": {"policy", "terms"},
    "forms": {"forms", "uploads"},
}
# A report finding's severity, as the analysis names it, to the tier it is shown in.
FINDING_TIERS = {"INTERVENE": "attention", "INFORM": "heads_up"}
TIER_RANK = ("all_clear", "heads_up", "attention", "act_now")


def report_urgency(findings: list[dict[str, Any]]) -> str:
    """The card takes the tier of its worst finding; none to show means all clear."""
    worst = "all_clear"
    for finding in findings:
        tier = FINDING_TIERS.get(str(finding.get("severity", "")).upper(), "")
        if tier and TIER_RANK.index(tier) > TIER_RANK.index(worst):
            worst = tier
    return worst


class DeepCheckWindow(QWidget):
    # The card has left the screen, whichever way: Done, the full report, or the close
    # control. Whatever was held back while it was up can come forward again.
    dismissed = Signal()

    def __init__(self, service: Any, mode: str = "system") -> None:
        super().__init__(None, FLOATING_FLAGS)
        self.service = service
        self.mode = mode
        self.colors = palette(mode)
        self.report: dict[str, Any] | None = None
        self.setWindowTitle(tr("deep_check"))
        make_floating(self)
        self.setStyleSheet(card_stylesheet(mode))
        self.setFixedWidth(CARD_WIDTH + 2 * SCREEN_MARGIN)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self.scroller: QScrollArea | None = None
        self.card: GuardianCard | None = None
        self.stage_glyphs: dict[str, QLabel] = {}
        self._show_running()

    # -- states ---------------------------------------------------------------

    def _reset_card(self, urgency: str = "note") -> GuardianCard:
        if self.scroller is not None:
            self._outer.removeWidget(self.scroller)
            self.scroller.deleteLater()
        self.card = GuardianCard(self.mode, urgency=urgency)
        self.card.closed.connect(self.close)
        self.scroller = scrollable(self.card)
        self._outer.addWidget(self.scroller)
        return self.card

    def _show_running(self) -> None:
        card = self._reset_card("note")
        card.add_header(title=tr("urgency_checking"), right=tr("app_name"))
        card.add_headline(tr("privacy_check"))
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
        card.add_context(tr("privacy_check"), self._origin())
        card.add_footer()
        self.status = card.headline_label or QLabel()
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
        # Only the things that need looking at. A card that spends half its height
        # listing what turned out fine makes the person hunt for the part that matters;
        # the all-clear sections are still there in the full report.
        findings = [
            finding
            for finding in report.get("findings", [])
            if str(finding.get("severity", "")).lower() != "ok"
        ]
        urgency = report_urgency(findings)
        card = self._reset_card(urgency)
        card.add_header(title=tr(f"urgency_{urgency}"), right=tr("app_name"))
        card.add_headline(str(report.get("summary", tr("check_complete"))))
        rows = [
            DecisionFinding(
                label=str(finding.get("summary", "")),
                severity="warn",
                detail=str(finding.get("detail", "")),
            )
            for finding in findings[:MAX_ROWS]
        ]
        # Each row wears its own tier's colour, so a red row stands out from the
        # amber ones around it instead of the whole list reading as one warning.
        accents = [
            urgency_palette(
                self.mode,
                FINDING_TIERS.get(str(finding.get("severity", "")).upper(), "heads_up"),
            )["accent"]
            for finding in findings[:MAX_ROWS]
        ]
        if len(findings) > MAX_ROWS:
            rows.append(
                DecisionFinding(
                    label=tr("more_findings", count=len(findings) - MAX_ROWS), severity="info"
                )
            )
        if not report.get("context_available"):
            rows.append(DecisionFinding(label=tr("no_context"), severity="info"))
        if rows:
            card.add_rows(rows, accents)
        card.add_context(tr("privacy_check"), self._origin(report))
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
        anchor_bottom_right(self, self.stack_content())

    def stack_content(self) -> QWidget | None:
        return self.scroller.widget() if self.scroller else None

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._anchor)

    def closeEvent(self, event: Any) -> None:
        release_surface(self)
        super().closeEvent(event)

    def hideEvent(self, event: Any) -> None:
        release_surface(self)
        super().hideEvent(event)
        self.dismissed.emit()
