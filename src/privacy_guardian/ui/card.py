"""The Privacy Guardian widget: one card, reused by every kind of intervention.

Layout, in the order the mockups put it:

    [lock] Privacy Guardian                                  origin   [x]
    Headline in bold
    Body paragraph
    [!] Finding row
        optional detail line
    ----------------------------------------------------------------
    subject  ->  destination
                                       tertiary (plain text, own row)
                              [ secondary ]   [ PRIMARY, filled ]
    ----------------------------------------------------------------
    [shield] Analysed on this device              Why am I seeing this?
    [==== countdown, informational cards only ====]
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QScreen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
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
from privacy_guardian.ui.theme import card_stylesheet, palette
from privacy_guardian.util.i18n import tr

CARD_WIDTH = 360
SCREEN_MARGIN = 24


def glyph(name: str, color: str, size: int = 15) -> QLabel:
    label = QLabel()
    label.setPixmap(icons.pixmap(name, color, size))
    label.setFixedWidth(size + 4)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    return label


def divider(color: str) -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {color}; border: none;")
    return line


class GuardianCard(QFrame):
    """A single card. Callers add the parts they need, in order."""

    closed = Signal()

    def __init__(self, mode: str = "system", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guardianCard")
        self.mode = mode
        self.colors = palette(mode)
        self.setStyleSheet(card_stylesheet(mode))
        self.setFixedWidth(CARD_WIDTH)
        self.buttons: dict[str, QPushButton] = {}
        self.progress: QProgressBar | None = None
        self.close_button: QPushButton | None = None
        self.why_button: QPushButton | None = None
        self.headline_label: QLabel | None = None
        self.body_label: QLabel | None = None
        self.rows_box: QVBoxLayout | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 0)
        self._layout.setSpacing(9)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 8)
        shadow.setColor(Qt.GlobalColor.black)
        self.setGraphicsEffect(shadow)

    # -- header ---------------------------------------------------------------

    def add_header(self, title: str = "", right: str = "", closable: bool = True) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        lock = QLabel()
        lock.setPixmap(icons.pixmap("padlock", self.colors["accent"], 16))
        row.addWidget(lock)
        name = QLabel(title or tr("app_name"))
        name.setObjectName("cardTitle")
        row.addWidget(name)
        row.addStretch(1)
        if right:
            origin = QLabel(right)
            origin.setObjectName("cardFooter")
            row.addWidget(origin)
        if closable:
            self.close_button = QPushButton()
            self.close_button.setProperty("tier", "icon")
            self.close_button.setIcon(icons.icon("close", self.colors["faint"]))
            self.close_button.setFlat(True)
            self.close_button.setFixedSize(18, 18)
            self.close_button.setAccessibleName(tr("close"))
            self.close_button.setToolTip(tr("close"))
            self.close_button.clicked.connect(self.closed.emit)
            row.addWidget(self.close_button)
        self._layout.addLayout(row)

    # -- text -----------------------------------------------------------------

    def add_headline(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardHeadline")
        label.setWordWrap(True)
        self.headline_label = label
        self._layout.addWidget(label)
        return label

    def add_body(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardBody")
        label.setWordWrap(True)
        self.body_label = label
        self._layout.addWidget(label)
        return label

    # -- finding rows ---------------------------------------------------------

    def add_rows(self, findings: list[DecisionFinding]) -> None:
        box = QVBoxLayout()
        box.setSpacing(6)
        box.setContentsMargins(0, 2, 0, 2)
        self.rows_box = box
        for finding in findings:
            box.addLayout(self.build_row(finding))
        self._layout.addLayout(box)

    def build_row(self, finding: DecisionFinding) -> QHBoxLayout:
        colors = {
            "warn": self.colors["warn"],
            "ok": self.colors["ok"],
            "info": self.colors["faint"],
        }
        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(glyph(finding.severity, colors.get(finding.severity, self.colors["faint"])))
        text = QVBoxLayout()
        text.setSpacing(1)
        label = QLabel(finding.label)
        label.setObjectName("cardRow")
        label.setWordWrap(True)
        text.addWidget(label)
        if finding.detail:
            detail = QLabel(finding.detail)
            detail.setObjectName("cardRowDetail")
            detail.setWordWrap(True)
            text.addWidget(detail)
        row.addLayout(text, 1)
        return row

    # -- context and actions --------------------------------------------------

    def add_context(self, subject: str, destination: str) -> None:
        if not subject and not destination:
            return
        self._layout.addWidget(divider(self.colors["line"]))
        row = QHBoxLayout()
        row.setSpacing(8)
        left = QLabel(subject)
        left.setObjectName("cardContext")
        row.addWidget(left)
        if destination:
            arrow = QLabel()
            arrow.setPixmap(icons.pixmap("arrow", self.colors["faint"], 14))
            row.addWidget(arrow)
            right = QLabel(destination)
            right.setObjectName("cardContext")
            row.addWidget(right)
        row.addStretch(1)
        self._layout.addLayout(row)

    def add_actions(
        self,
        actions: list[str],
        labels: dict[str, str],
        primary: str,
        tertiary: str,
        on_click: Callable[[str], None],
    ) -> None:
        """One row when the buttons fit; otherwise the escape hatch lifts to its own line."""

        def make(action: str, tier: str) -> QPushButton:
            button = QPushButton(labels.get(action, tr(action)))
            button.setProperty("tier", tier)
            button.setAccessibleName(button.text())
            button.clicked.connect(lambda _checked=False, value=action: on_click(value))
            self.buttons[action] = button
            return button

        ordered = [action for action in actions if action not in (tertiary, primary)]
        widgets = [make(action, "secondary") for action in ordered]
        if primary in actions:
            widgets.append(make(primary, "primary"))
        escape = make(tertiary, "tertiary") if tertiary and tertiary in actions else None
        available = CARD_WIDTH - 36
        needed = sum(w.sizeHint().width() for w in widgets) + 8 * max(0, len(widgets) - 1)
        if escape is not None and needed + escape.sizeHint().width() + 8 <= available:
            widgets.insert(0, escape)
            escape = None
        if escape is not None:
            above = QHBoxLayout()
            above.addStretch(1)
            above.addWidget(escape)
            self._layout.addLayout(above)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        for widget in widgets:
            row.addWidget(widget)
        self._layout.addLayout(row)

    # -- footer ---------------------------------------------------------------

    def add_footer(self, on_why: Callable[[], None] | None = None) -> None:
        self._layout.addSpacing(2)
        self._layout.addWidget(divider(self.colors["line"]))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 10)
        row.setSpacing(6)
        shield = QLabel()
        shield.setPixmap(icons.pixmap("shield", self.colors["faint"], 13))
        row.addWidget(shield)
        note = QLabel(tr("analysed_locally"))
        note.setObjectName("cardFooter")
        row.addWidget(note)
        row.addStretch(1)
        if on_why is not None:
            self.why_button = QPushButton(tr("why"))
            self.why_button.setProperty("tier", "link")
            self.why_button.setAccessibleName(tr("why"))
            self.why_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.why_button.clicked.connect(on_why)
            row.addWidget(self.why_button)
        self._layout.addLayout(row)

    def add_countdown(self, milliseconds: int) -> QProgressBar:
        """The thin bar along the bottom edge of an informational card."""
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setRange(0, milliseconds)
        bar.setValue(milliseconds)
        bar.setFixedHeight(3)
        self.progress = bar
        self._layout.setContentsMargins(18, 16, 18, 10)
        self._layout.addWidget(bar)
        return bar

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        self._layout.addLayout(layout)

    def finish(self) -> None:
        """Close the bottom margin when the card has no footer of its own."""
        self._layout.setContentsMargins(18, 16, 18, 16)


def scrollable(card: GuardianCard) -> QScrollArea:
    """Hold the card in a transparent scroller so a tall one can never overflow the screen.

    The card keeps its margin inside the scrolled content, which leaves the drop shadow
    room to draw and means the scrollbar only appears when the card really is too tall.
    """
    container = QWidget()
    container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN, SCREEN_MARGIN)
    layout.addWidget(card)
    area = QScrollArea()
    area.setWidget(container)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.viewport().setAutoFillBackground(False)
    area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
    return area


def target_screen(widget: QWidget) -> QScreen | None:
    """The screen the person is working on, not whichever one macOS calls primary."""
    return (
        QGuiApplication.screenAt(QCursor.pos())
        or widget.screen()
        or QGuiApplication.primaryScreen()
    )


def keep_above_dock(widget: QWidget) -> None:
    """Float the window above the Dock.

    Qt's always-on-top maps to NSFloatingWindowLevel (3), which is below the Dock (20),
    so a widget pinned to the bottom of the screen disappears behind the Dock the moment
    it slides up. An auto-hiding Dock makes this worse: availableGeometry() then reports
    the whole height as usable, so the widget is anchored right where the Dock appears.
    A warning the person cannot see or click is worse than no warning.
    """
    if sys.platform != "darwin" or not widget.isVisible():
        # winId() would force a native handle early; the level is reapplied on show.
        return
    try:
        import objc
        from AppKit import NSStatusWindowLevel

        view = objc.objc_object(c_void_p=int(widget.winId()))
        window = view.window()
        if window is not None:
            window.setLevel_(NSStatusWindowLevel)
    except Exception:
        # Placement still works without it; the Dock may simply overlap the widget.
        logging.getLogger(__name__).debug("window level unchanged")


def anchor_bottom_right(widget: QWidget, content: QWidget | None = None) -> None:
    """Pin the window to the bottom-right of the usable screen area.

    Two things have to happen before the move, or the window lands partly off screen
    and underneath the Dock, which draws above an always-on-top tool window:

    * the layout has to be activated, because a word-wrapped label reports far too
      small a height until it has been laid out at its real width, and
    * the height has to be capped to the space actually available.
    """
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    screen = target_screen(widget)
    if screen is None:
        widget.adjustSize()
        return
    rect = screen.availableGeometry()
    wanted = (content or widget).sizeHint()
    width = min(max(wanted.width(), widget.minimumWidth()), rect.width())
    height = min(max(wanted.height(), widget.minimumHeight()), rect.height())
    widget.resize(width, height)
    widget.move(
        max(rect.left(), rect.right() - width + 1),
        max(rect.top(), rect.bottom() - height + 1),
    )
    keep_above_dock(widget)
