from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from privacy_guardian.engine.preferences import Preference, default_categories
from privacy_guardian.llm.catalog import SUGGESTED_MODELS, ConnectionCheck, flash_models
from privacy_guardian.ui import icons
from privacy_guardian.ui.theme import palette, stylesheet
from privacy_guardian.util.i18n import tr

# Settings shows the kinds of information a person recognises, not the detector taxonomy.
PREFERENCE_ROWS = (
    "medical",
    "government_id",
    "location_precise",
    "phone",
    "email",
    "analytics",
    "advertising",
)
SECTIONS = ("overview", "events", "settings", "sites_and_apps")
# The Overview tiles, in reading order: three across, two down.
TALLY_TILES = ("requesters", "trackers", "files", "documents", "banners", "permissions")
# An ordinary adult reading pace, used only to turn analysed words into a time.
READING_WORDS_PER_MINUTE = 230
# What the outcome meant in practice, in the words the event history uses.
DECISION_WORDS = {
    "cancel": "Did not share",
    "continue": "Allowed",
    "redact": "Created redacted copy",
    "strip_metadata": "Removed location first",
    "unredact": "Restored original",
    "review_fields": "Reviewed fields",
    "reject_optional": "Rejected optional",
    "block": "Blocked identifiers",
    "clear_clipboard": "Cleared clipboard",
    "open_settings": "Opened settings",
    "mark_expected": "Marked expected",
    "view_details": "Viewed details",
}


def _label(text: str, role: str = "") -> QLabel:
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(role in {"body", "subtitle", "muted"})
    return label


def _card(*children: QWidget | QVBoxLayout | QHBoxLayout) -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    for child in children:
        if isinstance(child, QWidget):
            layout.addWidget(child)
        else:
            layout.addLayout(child)
    return frame


def _scroller(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(inner)
    return area


def _when(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    moment = moment.astimezone()
    today = datetime.now().astimezone().date()
    clock = moment.strftime("%H:%M")
    delta = (today - moment.date()).days
    if delta == 0:
        return tr("today", time=clock)
    if delta == 1:
        return tr("yesterday", time=clock)
    return moment.strftime("%d %b %H:%M")


def _date(value: str) -> str:
    """A day, not a moment: the tally starts at a date, and the year only when it is not this one."""
    try:
        moment = datetime.fromisoformat(value).astimezone()
    except (TypeError, ValueError):
        return value
    return moment.strftime("%d %b" if moment.year == datetime.now().year else "%d %b %Y").lstrip(
        "0"
    )


def _count(count: int, noun: str) -> str:
    """'1 site', '12 sites': the singular sits under noun_<x>, the plural under noun_<x>s."""
    return f"{count:,} " + tr("noun_" + noun + ("" if count == 1 else "s"))


def _duration(words: int) -> str:
    minutes = max(1, round(words / READING_WORDS_PER_MINUTE))
    if minutes < 60:
        return tr("minutes_short", count=minutes)
    return tr("hours_short", hours=minutes // 60, minutes=minutes % 60)


class Dashboard(QWidget):
    """The optional window: history, settings and the full thorough-check report."""

    def __init__(self, service: Any) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle(tr("app_name"))
        self.resize(940, 620)
        self.colors = palette()
        self.setStyleSheet(stylesheet())
        self.report: dict[str, Any] | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._overview_pane())
        self.stack.addWidget(self._events_pane())
        self.stack.addWidget(self._settings_pane())
        self.stack.addWidget(self._sites_pane())
        self.select("overview")

        self.history.cellDoubleClicked.connect(self.show_event_detail)
        self.requester_filter.textChanged.connect(self.refresh)
        self.outcome_filter.currentIndexChanged.connect(self.refresh)
        self.theme.currentIndexChanged.connect(self._apply_theme)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    # -- chrome ---------------------------------------------------------------

    def _sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setProperty("role", "sidebar")
        frame.setFixedWidth(216)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(3)
        brand = QHBoxLayout()
        brand.setSpacing(8)
        lock = QLabel()
        lock.setPixmap(icons.pixmap("padlock", self.colors["accent"], 17))
        brand.addWidget(lock)
        name = _label(tr("app_name"), "section")
        brand.addWidget(name)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(14)
        self.nav: dict[str, QPushButton] = {}
        for section in SECTIONS:
            button = QPushButton(tr(section).replace("&", "&&"))
            button.setProperty("tier", "nav")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, name=section: self.select(name))
            layout.addWidget(button)
            self.nav[section] = button
        layout.addStretch(1)
        return frame

    def select(self, section: str) -> None:
        """Nav is also the public entry point: show_dashboard('settings') lands here."""
        aliases = {"history": "events", "preferences": "settings"}
        section = aliases.get(section, section)
        if section not in SECTIONS:
            section = "overview"
        self.stack.setCurrentIndex(SECTIONS.index(section))
        for name, button in self.nav.items():
            button.setProperty("selected", "true" if name == section else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    @property
    def current_section(self) -> str:
        return SECTIONS[self.stack.currentIndex()]

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(_label(title, "h1"))
        if subtitle:
            layout.addWidget(_label(subtitle, "subtitle"))
        layout.addSpacing(6)
        return page, layout

    # -- overview -------------------------------------------------------------

    def _overview_pane(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(_label(tr("app_name"), "h1"))
        self.overview_status = _label(tr("overview_quiet"), "section")
        self.overview_body = _label(tr("overview_quiet_body"), "body")
        layout.addWidget(self.overview_status)
        layout.addWidget(self.overview_body)
        layout.addSpacing(10)
        # The tally: what has passed through the app, as Brave's new-tab page counts what
        # it blocked. Each tile is one number and one line saying what it is made of.
        self.tally_caption = _label("", "muted")
        self.tally_caption.setWordWrap(False)
        self.overview_state = _label("", "muted")
        self.overview_state.setWordWrap(False)
        self.overview_state.setAlignment(Qt.AlignmentFlag.AlignRight)
        caption = QHBoxLayout()
        caption.addWidget(self.tally_caption, 1)
        caption.addWidget(self.overview_state)
        layout.addLayout(caption)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.tally_tiles: dict[str, tuple[QLabel, QLabel]] = {}
        for index, key in enumerate(TALLY_TILES):
            value = _label("0", "metric")
            detail = _label("", "muted")
            self.tally_tiles[key] = (value, detail)
            # A tile whose second line wraps must not push its number out of line
            # with its neighbours': every tile in a row is as tall as the tallest.
            stack = QVBoxLayout()
            stack.setSpacing(8)
            for widget in (_label(tr("tally_" + key), "column"), value, detail):
                stack.addWidget(widget)
            stack.addStretch(1)
            tile = _card(stack)
            tile.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            grid.addWidget(tile, *divmod(index, 3))
        for column in range(3):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        layout.addSpacing(10)
        layout.addWidget(_label(tr("your_decisions"), "section"))
        self.decision_box = QVBoxLayout()
        self.decision_box.setSpacing(6)
        self.no_decisions = _label(tr("no_decisions"), "muted")
        self.decision_box.addWidget(self.no_decisions)
        self._decided_shown: dict[str, dict[str, int]] | None = None
        layout.addWidget(_card(self.decision_box))
        layout.addSpacing(4)
        row = QHBoxLayout()
        check = QPushButton(tr("run_check_now"))
        check.setProperty("tier", "primary")
        check.clicked.connect(lambda: self.service.deep_check())
        row.addWidget(check)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return _scroller(inner)

    def show_tally(self, tally: dict[str, Any]) -> None:
        """Put the store's tally on the tiles; every line comes from a stored record."""
        since = tally.get("since", "")
        self.tally_caption.setText(
            tr("tally_since", when=_date(str(since))) if since else tr("tally_empty")
        )
        tiles = {
            "requesters": (
                tally["sites"] + tally["apps"],
                tr(
                    "tally_requesters_detail",
                    sites=_count(tally["sites"], "site"),
                    apps=_count(tally["apps"], "app"),
                ),
            ),
            "trackers": (
                tally["trackers"],
                tr(
                    "tally_trackers_fingerprinting"
                    if tally["fingerprinting_sites"]
                    else "tally_trackers_detail",
                    networks=_count(tally["tracker_networks"], "network"),
                    sites=_count(tally["tracked_sites"], "site"),
                    fingerprinting=tally["fingerprinting_sites"],
                ),
            ),
            "files": (
                tally["files"],
                tr("tally_files_detail", count=tally["sensitive_files"]),
            ),
            "documents": (
                tally["policies"] + tally["terms"],
                tr("tally_documents_reading", time=_duration(tally["document_words"]))
                if tally["document_words"]
                else tr(
                    "tally_documents_detail",
                    policies=_count(tally["policies"], "policy"),
                    terms=_count(tally["terms"], "terms"),
                ),
            ),
            "banners": (
                tally["banners"],
                tr("tally_banners_detail", sites=_count(tally["banner_sites"], "site")),
            ),
            "permissions": (
                tally["grants"],
                tr(
                    "tally_permissions_detail",
                    grants=_count(tally["grants"], "grant"),
                    apps=_count(tally["granted_apps"], "app"),
                ),
            ),
        }
        for key, (count, detail) in tiles.items():
            value, caption = self.tally_tiles[key]
            value.setText(f"{count:,}")
            caption.setText(detail)
        decided = tally.get("decided", {})
        if decided == self._decided_shown:
            return
        self._decided_shown = decided
        while self.decision_box.count():
            item = self.decision_box.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.no_decisions:
                widget.deleteLater()
        self.no_decisions.setVisible(not decided)
        self.decision_box.addWidget(self.no_decisions)
        # Most-taken first, and only what was taken: a list of zeros says nothing.
        for action, figures in sorted(decided.items(), key=lambda pair: -pair[1]["count"]):
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            row.setSpacing(8)
            row.addWidget(_label(tr("decided_" + action)), 1)
            if figures.get("automatic"):
                row.addWidget(_label(tr("automatic_count", count=figures["automatic"]), "muted"))
            count = _label(f"{figures['count']:,}", "section")
            count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count.setMinimumWidth(48)
            row.addWidget(count)
            holder = QWidget()
            holder.setLayout(row)
            # The row is a grouping, not a surface: it takes the card's background.
            holder.setStyleSheet("background: transparent;")
            self.decision_box.addWidget(holder)

    def _metric_row(self) -> tuple[QHBoxLayout, dict[str, QLabel]]:
        row = QHBoxLayout()
        row.setSpacing(12)
        values: dict[str, QLabel] = {}
        for key in ("intervened", "informed", "ignored"):
            value = _label("0", "metric")
            values[key] = value
            row.addWidget(_card(_label(tr(key), "column"), value), 1)
        return row, values

    # -- events ---------------------------------------------------------------

    def _events_pane(self) -> QWidget:
        page, layout = self._page(
            tr("events"), tr("events_subtitle", days=self.service.settings.retention_days)
        )
        self.event_counts = self._metric_row()
        layout.addLayout(self.event_counts[0])
        layout.addSpacing(6)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.requester_filter = QLineEdit()
        self.requester_filter.setPlaceholderText(tr("filter"))
        self.outcome_filter = QComboBox()
        self.outcome_filter.addItems([tr("all"), "IGNORE", "INFORM", "INTERVENE"])
        filters.addWidget(self.requester_filter, 1)
        filters.addWidget(self.outcome_filter)
        layout.addLayout(filters)
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(
            [tr("column_time"), tr("column_what"), tr("column_where"), tr("column_decision")]
        )
        self.history.verticalHeader().setVisible(False)
        self.history.setShowGrid(False)
        self.history.setAlternatingRowColors(False)
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.setWordWrap(True)
        header = self.history.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.history, 1)
        self.empty_history = _label(tr("no_events"), "muted")
        layout.addWidget(self.empty_history)
        return page

    # -- preferences ----------------------------------------------------------

    def _settings_pane(self) -> QWidget:
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(12)
        outer.addWidget(_label(tr("settings"), "h1"))
        outer.addWidget(_label(tr("settings_subtitle"), "subtitle"))
        outer.addSpacing(6)

        heading = QHBoxLayout()
        heading.addWidget(_label(tr("information").upper(), "column"), 1)
        heading.addWidget(_label(tr("default_behaviour").upper(), "column"))
        outer.addLayout(heading)
        self.category_controls: dict[str, QComboBox] = {}
        defaults = default_categories()
        for category in PREFERENCE_ROWS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 4, 0, 4)
            row.addWidget(_label(tr(category)), 1)
            combo = QComboBox()
            combo.setFixedWidth(150)
            for preference in Preference:
                combo.addItem(tr(preference.value), preference.value)
            current = self.service.core.preferences.categories.get(
                category, defaults.get(category, Preference.ASK)
            )
            combo.setCurrentIndex(combo.findData(Preference(current).value))
            combo.currentIndexChanged.connect(self.save_preferences)
            row.addWidget(combo)
            self.category_controls[category] = combo
            outer.addLayout(row)
            line = QFrame()
            line.setProperty("role", "divider")
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {self.colors['line']}; border: none;")
            outer.addWidget(line)

        self.learning_enabled = QCheckBox(tr("learning_suggest"))
        self.learning_enabled.setChecked(self.service.settings.learning_enabled)
        self.learning_enabled.toggled.connect(self.save_settings)
        self.retention_enabled = QCheckBox(
            tr("learning_retention", days=self.service.settings.retention_days)
        )
        self.retention_enabled.setChecked(self.service.settings.retention_days > 0)
        self.retention_enabled.toggled.connect(self.save_settings)
        outer.addSpacing(8)
        outer.addWidget(
            _card(_label(tr("learning"), "section"), self.learning_enabled, self.retention_enabled)
        )

        outer.addSpacing(8)
        outer.addWidget(_label(tr("application"), "section"))
        form = QFormLayout()
        form.setSpacing(8)
        self.retention = QSpinBox()
        self.retention.setRange(1, 3650)
        self.retention.setValue(self.service.settings.retention_days)
        self.autostart = QCheckBox()
        self.autostart.setChecked(self.service.settings.autostart)
        self.llm_enabled = QCheckBox()
        self.llm_enabled.setChecked(self.service.settings.llm.enabled)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        # A closed list of Flash models: the tier whose cost suits a few short requests per
        # page. A successful test replaces it with the Flash models the key can really call.
        self.model = QComboBox()
        self.set_models(SUGGESTED_MODELS, self.service.settings.llm.model)
        self.llm_test = QPushButton(tr("llm_test"))
        self.llm_test.clicked.connect(self.test_llm)
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.llm_test)
        self.llm_status = _label("", "muted")
        self.llm_status.setWordWrap(True)
        self.hotkey = QLineEdit(self.service.settings.hotkey)
        self.theme = QComboBox()
        self.theme.addItems([tr("system"), tr("light"), tr("dark")])
        self.model.setAccessibleName(tr("llm_model"))
        self.llm_test.setAccessibleName(tr("llm_test"))
        for key, widget in (
            ("retention", self.retention),
            ("autostart", self.autostart),
            ("llm_enable", self.llm_enabled),
            ("api_key", self.api_key),
        ):
            widget.setAccessibleName(tr(key))
            form.addRow(tr(key), widget)
        # Key, model and the way to prove they work belong together: a key that is
        # present is not a key that works, and a model name that reads like a real one is
        # not one this account can call.
        form.addRow(tr("llm_model"), model_row)
        form.addRow("", self.llm_status)
        for key, control in (("hotkey", self.hotkey), ("theme", self.theme)):
            control.setAccessibleName(tr(key))
            form.addRow(tr(key), control)
        self.llm_toggles: dict[str, QCheckBox] = {}
        for key in (
            "policy_refinement",
            "purpose_refinement",
            "explanation_polishing",
            "deep_check_narrative",
        ):
            toggle = QCheckBox(tr(key))
            toggle.setChecked(getattr(self.service.settings.llm, key))
            form.addRow(toggle)
            self.llm_toggles[key] = toggle
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level.setCurrentText(self.service.settings.log_level)
        form.addRow(tr("log_level"), self.log_level)
        self.reject_optional = QCheckBox(tr("reject_optional"))
        self.reject_optional.setChecked(self.service.settings.reject_optional_cookies)
        form.addRow(self.reject_optional)
        outer.addLayout(form)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        save = QPushButton(tr("save"))
        save.setProperty("tier", "primary")
        save.clicked.connect(self.save_settings)
        buttons.addWidget(save)
        for key, callback in (
            ("export", self.export_preferences),
            ("import", self.import_preferences),
            ("reset", self.reset_preferences),
            ("update_trackers", lambda: self.service.update_trackers()),
        ):
            button = QPushButton(tr(key))
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch(1)
        outer.addLayout(buttons)
        outer.addStretch(1)
        return _scroller(inner)

    # -- sites & apps ---------------------------------------------------------

    def _sites_pane(self) -> QWidget:
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(10)
        self.site_title = _label(tr("sites_and_apps"), "h1")
        self.site_subtitle = _label(tr("no_check_yet"), "subtitle")
        outer.addWidget(self.site_title)
        outer.addWidget(self.site_subtitle)
        outer.addSpacing(4)
        self.report_box = QVBoxLayout()
        self.report_box.setSpacing(10)
        outer.addLayout(self.report_box)
        run = QHBoxLayout()
        button = QPushButton(tr("run_check_now"))
        button.setProperty("tier", "primary")
        button.clicked.connect(lambda: self.service.deep_check())
        run.addWidget(button)
        run.addStretch(1)
        outer.addLayout(run)
        outer.addStretch(1)
        # The stored profile and the raw preference document are still read and written
        # through these, so nothing behind them has gone; they are simply off the page.
        # Someone reading their own privacy report has no use for a JSON editor, and a
        # pane that ends in one reads as a debugging console rather than an answer.
        self.profile_key = QLineEdit(inner)
        self.profile_key.setPlaceholderText(tr("profile_key"))
        self.profile_key.hide()
        self.profile_detail = QTextEdit(inner)
        self.profile_detail.setReadOnly(True)
        self.profile_detail.hide()
        self.memory = QTextEdit(inner)
        self.memory.hide()
        return _scroller(inner)

    def show_report(self, report: dict[str, Any]) -> None:
        """Render a thorough-check result as the grouped cards the mockups show."""
        self.report = report
        origin = str(report.get("origin", "")) or tr("unknown")
        self.site_title.setText(origin)
        self.site_subtitle.setText(
            tr("thorough_check_ran", when=_when(str(report.get("ran_at", ""))))
        )
        while self.report_box.count():
            item = self.report_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for group in report.get("groups", []):
            rows: list[QWidget | QVBoxLayout | QHBoxLayout] = [
                _label(str(group.get("title", "")), "section")
            ]
            for entry in group.get("rows", []):
                rows.append(self._report_row(entry))
            self.report_box.addWidget(_card(*rows))
        self.select("sites_and_apps")

    def _report_row(self, entry: dict[str, Any]) -> QHBoxLayout:
        severity = str(entry.get("severity", "info"))
        colors = {"warn": self.colors["warn"], "ok": self.colors["ok"]}
        row = QHBoxLayout()
        row.setSpacing(9)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(severity, colors.get(severity, self.colors["faint"]), 15))
        glyph.setAlignment(Qt.AlignmentFlag.AlignTop)
        glyph.setFixedWidth(19)
        row.addWidget(glyph)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(_label(str(entry.get("summary", ""))))
        if entry.get("detail"):
            text.addWidget(_label(str(entry["detail"]), "body"))
        row.addLayout(text, 1)
        return row

    # -- lifecycle ------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()
        self.timer.start(3000)

    def hideEvent(self, event: QHideEvent) -> None:
        self.timer.stop()
        super().hideEvent(event)

    def _apply_theme(self, index: int) -> None:
        mode = ["system", "light", "dark"][index]
        self.colors = palette(mode)
        self.setStyleSheet(stylesheet(mode))

    def refresh(self) -> None:
        rows = self.service.core.store.history(
            requester=self.requester_filter.text() or None,
            outcome=self.outcome_filter.currentText()
            if self.outcome_filter.currentIndex()
            else None,
        )
        self.history.setRowCount(len(rows))
        for index, row in enumerate(rows):
            event, decision = row["event"], row["decision"] or {}
            summary = str(decision.get("headline") or decision.get("explanation", ""))
            cells = (
                _when(str(event.get("ts", ""))),
                summary,
                str(event["requester"].get("display_name", "")),
                DECISION_WORDS.get(str(row.get("action", "")), str(row.get("action", "")) or "—"),
            )
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if column == 1:
                    severity = "warn" if decision.get("outcome") == "INTERVENE" else "ok"
                    item.setIcon(
                        icons.icon(
                            severity,
                            self.colors["warn"] if severity == "warn" else self.colors["ok"],
                            sizes=(15,),
                        )
                    )
                item.setToolTip(str(decision.get("explanation", "")))
                self.history.setItem(index, column, item)
        self.history.resizeRowsToContents()
        self.empty_history.setVisible(not rows)
        counts = self.service.core.store.outcome_counts()
        for key, target in (("intervened", "INTERVENE"), ("informed", "INFORM")):
            self.event_counts[1][key].setText(str(counts.get(target, 0)))
        self.event_counts[1]["ignored"].setText(str(counts.get("IGNORE", 0)))
        attention = counts.get("INTERVENE", 0) + counts.get("INFORM", 0)
        self.overview_status.setText(
            tr("overview_quiet") if not attention else tr("overview_attention", count=attention)
        )
        self.show_tally(self.service.core.store.tally())
        browsers = len(getattr(self.service.core, "connected_browsers", {}) or {})
        permissions = self.service.permissions_status()
        granted = sum(1 for value in permissions.values() if value)
        self.overview_state.setText(
            f"{tr('browsers_connected')}: {browsers}  ·  "
            f"{tr('desktop_monitoring')}: {granted}/{len(permissions) or 1}"
        )
        self.memory.setPlainText(json.dumps(self.service.core.store.export_preferences(), indent=2))

    # -- actions --------------------------------------------------------------

    def save_preferences(self) -> None:
        self.service.core.preferences.categories.update(
            {
                category: Preference(combo.currentData())
                for category, combo in self.category_controls.items()
            }
        )
        self.service.core.store.set_preference(
            "user", self.service.core.preferences.model_dump(mode="json")
        )

    def export_preferences(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, tr("export"), "preferences.json", "JSON (*.json)"
        )
        if filename:
            Path(filename).write_text(
                json.dumps(self.service.core.store.export_preferences(), indent=2), encoding="utf-8"
            )

    def _load_preferences(self, payload: dict[str, Any]) -> None:
        from privacy_guardian.engine.preferences import LearnedRules, UserPreferences

        preferences = UserPreferences.model_validate(payload.get("preferences", {}).get("user", {}))
        learned = LearnedRules.model_validate(payload.get("learned_rules", {}).get("user", {}))
        self.service.core.store.import_preferences(payload)
        self.service.core.preferences = preferences
        self.service.core.learned_rules = learned
        self.service.settings.reject_optional_cookies = preferences.reject_optional_cookies
        self.service.settings.clipboard_allowlist = preferences.clipboard_allowlist
        self.service.settings.save()
        if getattr(self.service, "clipboard", None):
            self.service.clipboard.allowlist = preferences.clipboard_allowlist
        for category, combo in self.category_controls.items():
            preference = preferences.categories.get(
                category, preferences.categories.get(category.split(".")[0], Preference.ASK)
            )
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(preference.value))
            combo.blockSignals(False)
        self.refresh()

    def import_preferences(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, tr("import"), "", "JSON (*.json)")
        if filename:
            try:
                self._load_preferences(json.loads(Path(filename).read_text()))
            except (OSError, ValueError, TypeError, AttributeError):
                QMessageBox.warning(self, tr("app_name"), tr("invalid_preferences"))

    def save_memory(self) -> None:
        try:
            self._load_preferences(json.loads(self.memory.toPlainText()))
        except (OSError, ValueError, TypeError, AttributeError):
            QMessageBox.warning(self, tr("app_name"), tr("invalid_preferences"))

    def view_profile(self) -> None:
        key = self.profile_key.text().strip()
        profile = self.service.core.store.get_profile(
            "site", key
        ) or self.service.core.store.get_profile("app", key)
        self.profile_detail.setPlainText(json.dumps(profile or {}, indent=2))

    def show_event_detail(self, row: int, _column: int) -> None:
        records = self.service.core.store.history(
            requester=self.requester_filter.text() or None,
            outcome=self.outcome_filter.currentText()
            if self.outcome_filter.currentIndex()
            else None,
        )
        if row < len(records):
            # The record is still gathered, but the pane that used to display it no
            # longer shows one, so sending the person there would be a dead end.
            self.profile_detail.setPlainText(json.dumps(records[row], indent=2))

    def reset_preferences(self) -> None:
        self.service.core.learned_rules.reset()
        self.service.core.store.set_learned_rule(
            "user", self.service.core.learned_rules.model_dump(mode="json")
        )
        self.refresh()

    def save_settings(self) -> None:
        from privacy_guardian.config import Settings

        try:
            Settings.valid_hotkey(self.hotkey.text())
            if self.api_key.text():
                from privacy_guardian.llm.client import set_api_key

                set_api_key(self.api_key.text())
                self.api_key.clear()
        except Exception:
            QMessageBox.warning(self, tr("app_name"), tr("settings_failed"))
            return
        settings = self.service.settings
        settings.retention_days = self.retention.value()
        settings.autostart = self.autostart.isChecked()
        settings.learning_enabled = self.learning_enabled.isChecked()
        settings.llm.enabled = self.llm_enabled.isChecked()
        settings.llm.model = self.model.currentText().strip() or settings.llm.model
        settings.hotkey = self.hotkey.text()
        settings.log_level = self.log_level.currentText()
        settings.reject_optional_cookies = self.reject_optional.isChecked()
        self.service.core.preferences.reject_optional_cookies = settings.reject_optional_cookies
        self.service.core.store.set_preference(
            "user", self.service.core.preferences.model_dump(mode="json")
        )
        for key, toggle in self.llm_toggles.items():
            setattr(settings.llm, key, toggle.isChecked())
        self.service.hotkey.stop()
        from privacy_guardian.sensors.hotkey import GlobalHotkey

        self.service.hotkey = GlobalHotkey(
            settings.hotkey, self.service.bridge.deep_check_requested.emit
        )
        self.service.hotkey.start()
        settings.save()
        if self.service.core.adapter:
            self.service.core.adapter.set_autostart(settings.autostart)
        self.service.core.store.purge(settings.retention_days)

    def set_models(self, names: Any, selected: str = "") -> None:
        """Offer the Flash models among these, keeping whatever is configured regardless."""
        current = selected or self.model.currentText().strip()
        options = list(dict.fromkeys([*flash_models(names), *([current] if current else [])]))
        self.model.clear()
        self.model.addItems(options)
        if current:
            self.model.setCurrentText(current)

    def test_llm(self) -> None:
        """Ask the configured model to answer, using the key typed here or the saved one."""
        model = self.model.currentText().strip()
        if not model:
            self.show_llm_result(ConnectionCheck(ok=False, reason="model_unavailable"))
            return
        self.llm_test.setEnabled(False)
        self._status_tone("muted")
        self.llm_status.setText(tr("llm_testing"))
        self.service.test_llm_connection(self.api_key.text().strip(), model)

    def _status_tone(self, role: str) -> None:
        """A failure that looks like a hint reads as one, so the colour follows the news."""
        self.llm_status.setProperty("role", role)
        style = self.llm_status.style()
        style.unpolish(self.llm_status)
        style.polish(self.llm_status)

    def show_llm_result(self, check: Any) -> None:
        self.llm_test.setEnabled(True)
        if not check.ok:
            self._status_tone("warn")
            self.llm_status.setText(
                tr("llm_test_failed", reason=tr("llm_reason_" + (check.reason or "api_status")))
            )
            return
        self._status_tone("muted")
        if check.models:
            self.set_models(check.models, check.model)
            message = tr(
                "llm_test_ok_listed",
                model=check.model,
                ms=check.latency_ms,
                count=len(check.models),
            )
        else:
            message = tr("llm_test_ok", model=check.model, ms=check.latency_ms)
        # A working key behind an unticked box is the one outcome that looks like success
        # and does nothing, so say so rather than letting them find out later.
        if not self.llm_enabled.isChecked():
            message += " " + tr("llm_not_enabled")
        self.llm_status.setText(message)
