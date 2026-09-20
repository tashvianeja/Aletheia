"""The thorough check, shown as the same floating card as every other intervention.

While it runs the card is a bar filling up under one line saying what is being looked at
right now; when it finishes it becomes a result summary with a way through to the full
report in the dashboard.
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

# As many findings as fit on a card that can still be read at a glance; the rest are
# one line away in the full report.
MAX_ROWS = 5
# The four parts of a run the bar counts off, and the parts of the run that answer for
# each. They are no longer listed on the card: a run takes a few seconds, and a list of
# four things that have not happened yet is a reading exercise, not progress.
STAGE_SOURCES = {
    "permissions": {"permissions"},
    "tracking": {"tracking", "consent"},
    "policy": {"policy", "terms"},
    "forms": {"forms", "uploads"},
}
STAGE_COUNT = len(STAGE_SOURCES)
# A part that has stopped moving, either way, counts towards the bar.
SETTLED = frozenset({"done", "unavailable"})
# What the check is doing at the moment each part of it reports in. Everything the page
# is asked for is asked for at once, so the six parts behind it share one line; the two
# longest waits in a run — collecting the page, and writing the summary afterwards —
# have their own words, because otherwise the card would sit there looking finished.
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
# One turn of the mark every 1.1 seconds or so: fast enough to read as alive, slow
# enough not to pull the eye away from whatever the person is actually doing.
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
        # Where each of the four parts the bar counts has got to, and the raw state of
        # every part of the run behind them — several parts can share one of the four.
        self.stage_states: dict[str, str] = {}
        self.source_states: dict[str, str] = {}
        self.activity: QLabel | None = None
        self.activity_glyph: QLabel | None = None
        self.tally: QLabel | None = None
        self.steps: QProgressBar | None = None
        # A bar that only moves four times in a run is still for seconds at a stretch,
        # and a still card is indistinguishable from a stuck one. The mark beside the
        # line turns for as long as the run really is going.
        self._complete = False
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
        self.activity = None
        self.activity_glyph = None
        self.tally = None
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
        self._complete = False
        self.stage_states = dict.fromkeys(STAGE_SOURCES, "pending")
        self.source_states = {}
        # What is being looked at right now, in one line, with a mark that turns beside
        # it and the count of how many of the four parts have answered. A run is over in
        # a few seconds; naming the one thing in hand is more use in that time than a
        # list of four, three of which are always "waiting".
        line = QHBoxLayout()
        line.setSpacing(9)
        self.activity_glyph = QLabel()
        self.activity_glyph.setFixedWidth(19)
        line.addWidget(self.activity_glyph)
        self.activity = QLabel(tr("checking_start"))
        self.activity.setObjectName("cardBody")
        self.activity.setWordWrap(True)
        line.addWidget(self.activity, 1)
        self.tally = QLabel()
        self.tally.setObjectName("cardContext")
        line.addWidget(self.tally)
        card.add_layout(line)
        # How far through the run is. With the list gone this is the only thing that
        # says so, so it is drawn as a bar rather than the hairline under a list.
        self.steps = QProgressBar()
        self.steps.setObjectName("checkProgress")
        self.steps.setTextVisible(False)
        self.steps.setRange(0, STAGE_COUNT)
        self.steps.setValue(0)
        self.steps.setFixedHeight(6)
        card.add_widget(self.steps)
        self._settle_steps()
        self._paint_activity()
        self._run_spinner()
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
        if isinstance(update, str) or self.card is None or self.steps is None:
            return
        stage = str(update.get("stage", ""))
        state = str(update.get("state", ""))
        # Every part of the run names itself as it starts; the two that only ever
        # report once, at their end, name themselves then.
        announces = state == "running" or (state == "done" and stage in {"complete", "summary"})
        if announces and stage in ACTIVITY and self.activity is not None:
            self.activity.setText(tr(ACTIVITY[stage]))
        if stage == "complete" and state == "done":
            self._complete = True
        if state:
            self.source_states[stage] = state
        for key, sources in STAGE_SOURCES.items():
            if stage in sources:
                self.stage_states[key] = self._folded(sources)
        self._settle_steps()
        if stage == "summary" and state == "running":
            # All four are answered by now and there is no way to know how long the
            # model will take: a busy bar says "still working" without claiming to
            # know how much of it is left, and a count of four out of four beside it
            # would say the opposite.
            self.steps.setRange(0, 0)
            if self.tally is not None:
                self.tally.setText("")
        self._run_spinner()

    def _folded(self, sources: set[str]) -> str:
        """One of the four can stand for several parts of the run; the furthest on wins.

        A part is answered as soon as anything behind it has an answer: tracking covers
        both the trackers on the page and the cookie banner, and a page with a banner
        but no trackers has still been checked for tracking.
        """
        states = {self.source_states.get(source, "pending") for source in sources}
        for state in ("done", "running", "unavailable"):
            if state in states:
                return state
        return "pending"

    def _paint_activity(self) -> None:
        # Decoration: the mark says only that the run is alive, which the moving bar
        # beside it says too. What is being checked, and how far through it is, are
        # both in words — the line itself, and the bar's name.
        if self.activity_glyph is not None:
            self.activity_glyph.setPixmap(
                icons.pixmap("running", self.colors["accent"], 15, turn=self._turn)
            )

    def _settle_steps(self) -> None:
        if self.steps is None:
            return
        done = sum(1 for state in self.stage_states.values() if state in SETTLED)
        self.steps.setRange(0, STAGE_COUNT)
        self.steps.setValue(done)
        self.steps.setAccessibleName(tr("checking_steps", done=done, total=STAGE_COUNT))
        if self.tally is not None:
            self.tally.setText(tr("checking_tally", done=done, total=STAGE_COUNT))

    def _run_spinner(self) -> None:
        """Turn for as long as the run is going, on a card someone can see.

        The run is going from the moment the card goes up until it says it is complete:
        the waits with nothing to count against them — collecting the page at the start,
        writing the summary at the end — are the longest ones, and they are exactly when
        a still card would look stuck. A check whose page was left behind takes its card
        down while the run carries on reporting in; there is nothing to animate for a
        card nobody can see, and the timer would outlive it by the length of the run.
        """
        if self.steps is not None and not self._complete and self.isVisible():
            if not self.spinner.isActive():
                self.spinner.start()
        else:
            self._stop_spinner()

    def _advance_spinner(self) -> None:
        self._turn = (self._turn + SPIN_DEGREES) % 360
        self._paint_activity()

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
        keeps the same headline and the same findings, and every one of them now reads
        as a verdict on a page that was never checked. There is no honest way to keep
        it on screen, so it goes.
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
        # Nothing turns on a card that is not on screen yet, and the card is built
        # before it is shown, so the mark starts here rather than at the first report.
        self._run_spinner()
        QTimer.singleShot(0, self._anchor)

    def closeEvent(self, event: Any) -> None:
        release_surface(self)
        super().closeEvent(event)

    def hideEvent(self, event: Any) -> None:
        self._stop_spinner()
        release_surface(self)
        super().hideEvent(event)
        self.dismissed.emit()
