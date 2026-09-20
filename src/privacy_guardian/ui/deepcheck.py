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
    QProgressBar,
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
# How each line is drawn in each of the states the check reports for it: waiting its
# turn, under way, answered, or not answerable here. The mark and the colour say the
# same thing, so the list is readable without relying on either alone.
STAGE_MARKS = {
    "pending": ("pending", "faint"),
    "running": ("running", "accent"),
    "done": ("ok", "ok"),
    "unavailable": ("info", "faint"),
}
# A line that has stopped moving, either way, counts towards the bar along the bottom.
SETTLED = frozenset({"done", "unavailable"})
# What the check is doing at the moment each part of it reports in. The two that have
# no line of their own — collecting the page, and writing the summary afterwards —
# are the longest waits in the whole run, so the card has to be able to say them.
ACTIVITY = {
    "start": "checking_start",
    "tracking": "checking_page",
    "consent": "checking_page",
    "policy": "checking_page",
    "terms": "checking_page",
    "forms": "checking_page",
    "uploads": "checking_page",
    "permissions": "checking_permissions",
    "summary": "checking_summary",
    "complete": "checking_finished",
}
# One turn of the spinner every 1.1 seconds or so: fast enough to read as alive,
# slow enough not to pull the eye away from whatever the person is actually doing.
SPIN_DEGREES = 30
SPIN_INTERVAL_MS = 90
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
        # The page this card answers for. Everything on it is about that one page, so
        # when the browser moves somewhere else the card has nothing left to say.
        self.origin = ""
        self.setWindowTitle(tr("deep_check"))
        make_floating(self)
        self.setStyleSheet(card_stylesheet(mode))
        self.setFixedWidth(CARD_WIDTH + 2 * SCREEN_MARGIN)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self.scroller: QScrollArea | None = None
        self.card: GuardianCard | None = None
        self.stage_glyphs: dict[str, QLabel] = {}
        self.stage_titles = dict(STAGES)
        # Where each line of the checklist has got to, and the raw state of every part
        # of the run behind it — several parts can share one line.
        self.stage_states: dict[str, str] = {}
        self.source_states: dict[str, str] = {}
        self.activity: QLabel | None = None
        self.steps: QProgressBar | None = None
        # A still list is indistinguishable from a stuck one. The line that is being
        # worked on turns, for as long as it is really being worked on.
        self._turn = 0.0
        self.spinner = QTimer(self)
        self.spinner.setInterval(SPIN_INTERVAL_MS)
        self.spinner.timeout.connect(self._advance_spinner)
        self._show_running()

    # -- states ---------------------------------------------------------------

    def _reset_card(self, urgency: str = "note") -> GuardianCard:
        # Whatever was spinning belongs to the card about to be thrown away; stop
        # before its labels go, not after.
        self._stop_spinner()
        self.stage_glyphs = {}
        self.activity = None
        self.steps = None
        if self.scroller is not None:
            self._outer.removeWidget(self.scroller)
            self.scroller.deleteLater()
        self.card = GuardianCard(self.mode, urgency=urgency)
        self.card.closed.connect(self.close)
        self.scroller = scrollable(self.card)
        self._outer.addWidget(self.scroller)
        return self.card

    def _show_running(self) -> None:
        self.report = None
        self.origin = self._origin()
        card = self._reset_card("note")
        card.add_header(title=tr("urgency_checking"), right=tr("app_name"))
        card.add_headline(tr("privacy_check"))
        # What is happening right now, in one line. The two longest waits in a run —
        # asking the page for its context, and writing the summary afterwards — have
        # no line of their own on the checklist, and without this the card would sit
        # there looking finished while it was still working.
        self.activity = card.add_body(tr("checking_start"))
        self.stage_states = dict.fromkeys(STAGE_SOURCES, "pending")
        self.source_states = {}
        box = QVBoxLayout()
        box.setSpacing(7)
        for key, title in STAGES:
            row = QHBoxLayout()
            row.setSpacing(9)
            glyph = QLabel()
            glyph.setFixedWidth(19)
            row.addWidget(glyph)
            label = QLabel(title)
            label.setObjectName("cardRow")
            row.addWidget(label, 1)
            box.addLayout(row)
            self.stage_glyphs[key] = glyph
            self._paint_stage(key)
        card.add_layout(box)
        # How far through the run is, along the bottom of the list. Three pixels of
        # colour: enough to see it move, not enough to read as a warning of its own.
        self.steps = QProgressBar()
        self.steps.setTextVisible(False)
        self.steps.setRange(0, len(STAGES))
        self.steps.setValue(0)
        self.steps.setFixedHeight(3)
        self.steps.setAccessibleName(tr("checking_steps", done=0, total=len(STAGES)))
        card.add_widget(self.steps)
        card.add_context(tr("privacy_check"), self.origin)
        card.add_footer()
        self.status = card.headline_label or QLabel()
        self._anchor()

    # -- progress --------------------------------------------------------------

    def show_progress(self, update: dict[str, str] | str) -> None:
        """Move the card on as each part of the check starts and reports in.

        Every part of a run says when it begins as well as when it ends, so a step
        that takes seconds is visibly taking them rather than appearing, finished,
        alongside every other step at the end.
        """
        if isinstance(update, str) or self.card is None or not self.stage_glyphs:
            return
        stage = str(update.get("stage", ""))
        state = str(update.get("state", ""))
        # Every part of the run names itself as it starts; the two that only ever
        # report once, at their end, name themselves then.
        announces = state == "running" or (state == "done" and stage in {"complete", "summary"})
        if announces and stage in ACTIVITY and self.activity is not None:
            self.activity.setText(tr(ACTIVITY[stage]))
        if state:
            self.source_states[stage] = state
        for key, sources in STAGE_SOURCES.items():
            if stage in sources:
                self._set_stage(key, self._folded(sources))
        self._settle_steps()
        if stage == "summary" and state == "running" and self.steps is not None:
            # Every line is answered by now and there is no way to know how long the
            # model will take: a busy bar says "still working" without claiming to
            # know how much of it is left.
            self.steps.setRange(0, 0)
        self._run_spinner()

    def _folded(self, sources: set[str]) -> str:
        """One line can stand for several parts of the run; the furthest on wins.

        A line is answered as soon as any part behind it has an answer: "Tracking"
        covers both the trackers on the page and the cookie banner, and a page with a
        banner but no trackers has still been checked for tracking.
        """
        states = {self.source_states.get(source, "pending") for source in sources}
        for state in ("done", "running", "unavailable"):
            if state in states:
                return state
        return "pending"

    def _set_stage(self, key: str, state: str) -> None:
        if self.stage_states.get(key) == state:
            return
        self.stage_states[key] = state
        self._paint_stage(key)

    def _paint_stage(self, key: str) -> None:
        glyph = self.stage_glyphs.get(key)
        if glyph is None:
            return
        state = self.stage_states.get(key, "pending")
        name, color = STAGE_MARKS.get(state, STAGE_MARKS["pending"])
        turn = self._turn if state == "running" else 0.0
        glyph.setPixmap(icons.pixmap(name, self.colors[color], 15, turn=turn))
        # The mark is the only thing that says where this line has got to, and a mark
        # is nothing to a screen reader; the line says it in words as well.
        glyph.setAccessibleName(f"{self.stage_titles.get(key, key)}: {tr('stage_' + state)}")

    def _settle_steps(self) -> None:
        if self.steps is None:
            return
        done = sum(1 for state in self.stage_states.values() if state in SETTLED)
        self.steps.setRange(0, len(STAGES))
        self.steps.setValue(done)
        self.steps.setAccessibleName(tr("checking_steps", done=done, total=len(STAGES)))

    def _run_spinner(self) -> None:
        """Turn only while something really is turning, on a card someone can see.

        A check whose page was left behind takes its card down while the run carries
        on reporting in; there is nothing to animate for a card that is no longer on
        screen, and the timer would outlive it by the length of the run.
        """
        running = any(state == "running" for state in self.stage_states.values())
        if running and self.isVisible():
            if not self.spinner.isActive():
                self.spinner.start()
        else:
            self._stop_spinner()

    def _advance_spinner(self) -> None:
        self._turn = (self._turn + SPIN_DEGREES) % 360
        for key, state in self.stage_states.items():
            if state == "running":
                self._paint_stage(key)

    def _stop_spinner(self) -> None:
        self.spinner.stop()
        self._turn = 0.0

    def show_report(self, report: dict[str, Any]) -> None:
        self.report = report
        self.origin = self._origin(report) or self.origin
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
                # Routine contract machinery is a note. Drawing a liability cap with the
                # same triangle as "your data can be sold" tells the reader they are the
                # same size of problem, and leaves them nothing to prioritise.
                severity="info" if str(finding.get("tone", "warn")) == "info" else "warn",
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
        card.add_context(tr("privacy_check"), self.origin)
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

    def page_changed(self, origin: str) -> None:
        """The browser is showing another page now, so this card is about the wrong one.

        A check is a reading of one page at one moment. Left up over the next tab it
        keeps the same headline, the same findings and the same tick marks, and every
        one of them now reads as a verdict on a page that was never checked. There is
        no honest way to keep it on screen, so it goes.
        """
        # An empty origin means the browser is not showing a web page at all — a blank
        # tab, its own settings, or a window that has never been focused — which is not
        # a reason to take a card away from someone who may be reading it. A card about
        # a desktop application is not about a tab either, and a browser behind it
        # changing page says nothing about the app in front.
        if not origin or origin == self.origin:
            return
        if not self.origin.startswith(("http://", "https://")):
            return
        self.close()

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
        # What the browser is showing right now, falling back to the page the last
        # analysis was about when no extension is reporting.
        return str(getattr(core, "active_origin", "") or getattr(core, "focused_origin", "") or "")

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
        self._stop_spinner()
        release_surface(self)
        super().hideEvent(event)
        self.dismissed.emit()
