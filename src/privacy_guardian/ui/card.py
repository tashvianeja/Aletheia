"""The Privacy Guardian widget: one card, reused by every kind of intervention.

Layout, in the order the mockups put it:

    ┃ [tier icon] ACT NOW / HEADS UP / ...    Privacy Guardian   [x] ┃  <- coloured band
    Headline in bold
    Body paragraph
    ┌ [!] Finding row                                              ┐  <- tinted box
    │     optional detail line                                     │
    └──────────────────────────────────────────────────────────────┘
    ----------------------------------------------------------------
    subject  ->  destination
                                       tertiary (plain text, own row)
                              [ secondary ]   [ PRIMARY, filled ]
    ----------------------------------------------------------------
    [shield] Analysed on this device              Why am I seeing this?
    [==== countdown, informational cards only ====]

The band's colour family is the card's urgency tier (see engine.presentation.urgency_for):
solid deep red for "act now", tinted red for "needs your attention", amber for a heads
up, green for all clear or handled, blue for a plain note.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QScreen
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
from privacy_guardian.ui.theme import card_stylesheet, palette, urgency_palette
from privacy_guardian.util.i18n import tr

CARD_WIDTH = 360
SCREEN_MARGIN = 24

# The window flags every floating surface in the corner shares.
#
# WindowDoesNotAcceptFocus matters more than it looks: on macOS it makes the panel
# non-activating, so a click on one of its buttons reaches the button. Without it the
# first click only activates the app, and because a Tool window is hidden by macOS
# the moment its app deactivates again, the card vanishes instead of answering. The
# person sees a button that does nothing and a card that disappears.
FLOATING_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


def make_floating(widget: QWidget) -> None:
    """Apply the attributes a corner surface needs, before its native window exists.

    Showing it must not pull focus from the page the person is on, and it must stay
    on screen whether or not this app happens to be the active one: a warning that
    hides itself when the person clicks back into their browser was never read.
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    widget.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)


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


BAND_ICONS = {
    "act_now": "stop",
    "attention": "warn",
    "heads_up": "alert",
    "all_clear": "ok",
    "note": "note",
}


def urgency_label(urgency: str, handled: bool = False) -> str:
    if urgency == "all_clear" and handled:
        return tr("urgency_handled")
    return tr(f"urgency_{urgency}") if urgency in BAND_ICONS else tr("app_name")


class UrgencyBand(QFrame):
    """The coloured strip across the top of the card.

    It is painted rather than styled so it can pulse: `glow` blends the band colour
    towards its brighter pulse colour, and an animation runs it up and down a few
    times when an "act now" card arrives. Motion is the one signal that reaches
    someone who is looking at something else, which is exactly when the card arrives.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cardBand")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._glow = 0.0
        self._base = QColor("#e8ecfd")
        self._bright = QColor("#c7d2fe")
        self.radius = 13

    def set_colors(self, base: str, bright: str) -> None:
        self._base = QColor(base)
        self._bright = QColor(bright)
        self.update()

    def get_glow(self) -> float:
        return self._glow

    def set_glow(self, value: float) -> None:
        self._glow = max(0.0, min(1.0, float(value)))
        self.update()

    glow = Property(float, get_glow, set_glow)  # type: ignore[call-arg]

    def paintEvent(self, event: Any) -> None:
        t = self._glow
        color = QColor(
            round(self._base.red() + (self._bright.red() - self._base.red()) * t),
            round(self._base.green() + (self._bright.green() - self._base.green()) * t),
            round(self._base.blue() + (self._bright.blue() - self._base.blue()) * t),
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        rect = QRectF(self.rect())
        r = float(self.radius)
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + r)
        path.arcTo(rect.left(), rect.top(), 2 * r, 2 * r, 180, -90)
        path.lineTo(rect.right() - r, rect.top())
        path.arcTo(rect.right() - 2 * r, rect.top(), 2 * r, 2 * r, 90, -90)
        path.lineTo(rect.right(), rect.bottom())
        path.closeSubpath()
        painter.fillPath(path, color)
        painter.end()


class GuardianCard(QFrame):
    """A single card. Callers add the parts they need, in order.

    Every card belongs to one urgency tier, and the tier decides the colour family of
    the band across the top, the icon and word on it, the outline of the card and the
    wash behind the findings. Someone glancing at the corner of their screen should
    know whether to stop or carry on before they have read a single sentence.
    """

    closed = Signal()

    def __init__(
        self, mode: str = "system", parent: QWidget | None = None, urgency: str = "note"
    ) -> None:
        super().__init__(parent)
        self.setObjectName("guardianCard")
        self.mode = mode
        self.colors = palette(mode)
        self.urgency = urgency if urgency in BAND_ICONS else "note"
        self.tone = urgency_palette(mode, self.urgency)
        self.setProperty("urgency", self.urgency)
        self.setStyleSheet(card_stylesheet(mode))
        self.setFixedWidth(CARD_WIDTH)
        self.buttons: dict[str, QPushButton] = {}
        self.progress: QProgressBar | None = None
        self.close_button: QPushButton | None = None
        self.why_button: QPushButton | None = None
        self.headline_label: QLabel | None = None
        self.body_label: QLabel | None = None
        self.band: UrgencyBand | None = None
        self.band_icon: QLabel | None = None
        self.band_label: QLabel | None = None
        self.rows_box: QVBoxLayout | None = None
        self.findings_box: QFrame | None = None
        self._pulse: QPropertyAnimation | None = None
        # The band bleeds to the card's edges; everything under it keeps the margin.
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._content = QVBoxLayout()
        self._content.setContentsMargins(18, 14, 18, 0)
        self._content.setSpacing(9)
        self._layout.addLayout(self._content)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 8)
        shadow.setColor(Qt.GlobalColor.black)
        self.setGraphicsEffect(shadow)

    # -- header ---------------------------------------------------------------

    def add_header(self, title: str = "", right: str = "", closable: bool = True) -> None:
        """The band: tier icon, the tier in words (or a title), who is speaking, close.

        The band is fixed at its natural height. Left to a layout it is the item that
        soaks up any slack, and a card whose rows are squeezed to make room for a
        taller band cuts the second line off the very finding the person needs.
        """
        band = UrgencyBand(self)
        band.radius = 12 if self.urgency == "act_now" else 13
        row = QHBoxLayout(band)
        row.setContentsMargins(14, 9, 12, 9)
        row.setSpacing(8)
        self.band_icon = QLabel()
        self.band_icon.setFixedWidth(20)
        row.addWidget(self.band_icon)
        self.band_label = QLabel(title or urgency_label(self.urgency))
        self.band_label.setObjectName("cardBandLabel")
        row.addWidget(self.band_label)
        row.addStretch(1)
        if right:
            origin = QLabel(right)
            origin.setObjectName("cardBandOrigin")
            origin.setMaximumWidth(150)
            row.addWidget(origin)
        if closable:
            self.close_button = QPushButton()
            self.close_button.setProperty("tier", "icon")
            self.close_button.setFlat(True)
            self.close_button.setFixedSize(18, 18)
            self.close_button.setAccessibleName(tr("close"))
            self.close_button.setToolTip(tr("close"))
            self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.close_button.clicked.connect(self.closed.emit)
            row.addWidget(self.close_button)
        self.band = band
        self._layout.insertWidget(0, band)
        self._paint_band()
        band.setFixedHeight(band.sizeHint().height())

    def _paint_band(self) -> None:
        """Colour the band and its contents for the current tier."""
        if self.band is None:
            return
        tone = self.tone
        self.band.set_colors(tone["band"], tone["pulse"])
        if self.band_icon is not None:
            name = BAND_ICONS[self.urgency]
            solid = self.urgency == "act_now"
            self.band_icon.setPixmap(
                icons.pixmap(
                    name,
                    tone["band_ink"] if solid else tone["accent"],
                    17,
                    inner=tone["band"] if solid else "#ffffff",
                )
            )
        if self.close_button is not None:
            self.close_button.setIcon(icons.icon("close", tone["band_dim"]))

    def set_urgency(self, urgency: str, label: str = "") -> None:
        """Move the card to another tier, restyling everything the tier decides."""
        self.urgency = urgency if urgency in BAND_ICONS else "note"
        self.tone = urgency_palette(self.mode, self.urgency)
        self.setProperty("urgency", self.urgency)
        self.style().unpolish(self)
        self.style().polish(self)
        if self.band_label is not None:
            self.band_label.setText(label or urgency_label(self.urgency))
        self._paint_band()

    def set_mode(self, mode: str) -> None:
        """Follow a light/dark switch without rebuilding the card."""
        self.mode = mode
        self.colors = palette(mode)
        self.tone = urgency_palette(mode, self.urgency)
        self.setStyleSheet(card_stylesheet(mode))
        self._paint_band()

    def pulse(self, times: int = 3) -> None:
        """Breathe the band a few times, then rest. Never indefinitely."""
        if self.band is None or times <= 0:
            return
        animation = QPropertyAnimation(self.band, QByteArray(b"glow"), self)
        animation.setDuration(800)
        animation.setKeyValueAt(0.0, 0.0)
        animation.setKeyValueAt(0.5, 1.0)
        animation.setKeyValueAt(1.0, 0.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        animation.setLoopCount(times)
        self._pulse = animation
        animation.start()

    # -- text -----------------------------------------------------------------

    def add_headline(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardHeadline")
        label.setWordWrap(True)
        self.headline_label = label
        self._content.addWidget(label)
        return label

    def add_body(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardBody")
        label.setWordWrap(True)
        self.body_label = label
        self._content.addWidget(label)
        return label

    # -- finding rows ---------------------------------------------------------

    def add_rows(self, findings: list[DecisionFinding], accents: list[str] | None = None) -> None:
        """The list of what was found, boxed together in the tier's wash.

        `accents` overrides the colour of individual warning rows, for a card that
        mixes tiers in one list (the thorough check does).
        """
        frame = QFrame()
        frame.setObjectName("findingsBox")
        box = QVBoxLayout(frame)
        box.setSpacing(7)
        box.setContentsMargins(11, 9, 11, 9)
        self.rows_box = box
        self.findings_box = frame
        for index, finding in enumerate(findings):
            accent = accents[index] if accents and index < len(accents) else None
            box.addLayout(self.build_row(finding, accent))
        self._content.addWidget(frame)

    def row_color(self, severity: str) -> str:
        """Warnings wear the tier's colour, so a red card has red rows, not amber."""
        if severity == "warn":
            return (
                self.tone["accent"]
                if self.urgency in ("act_now", "attention")
                else (self.colors["warn"])
            )
        if severity == "ok":
            return self.colors["ok"]
        return self.colors["faint"]

    def build_row(self, finding: DecisionFinding, accent: str | None = None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(glyph(finding.severity, accent or self.row_color(finding.severity)))
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
        self._content.addWidget(divider(self.colors["line"]))
        row = QHBoxLayout()
        row.setSpacing(8)
        left = QLabel(subject)
        left.setObjectName("cardContextStrong")
        row.addWidget(left)
        if destination:
            arrow = QLabel()
            arrow.setPixmap(icons.pixmap("arrow", self.colors["faint"], 14))
            row.addWidget(arrow)
            right = QLabel(destination)
            right.setObjectName("cardContext")
            row.addWidget(right)
        row.addStretch(1)
        self._content.addLayout(row)

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
            button.setCursor(Qt.CursorShape.PointingHandCursor)
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
            self._content.addLayout(above)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        for widget in widgets:
            row.addWidget(widget)
        self._content.addLayout(row)

    # -- footer ---------------------------------------------------------------

    def add_footer(self, on_why: Callable[[], None] | None = None) -> None:
        self._content.addSpacing(2)
        self._content.addWidget(divider(self.colors["line"]))
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
        self._content.addLayout(row)

    def add_countdown(self, milliseconds: int) -> QProgressBar:
        """The thin bar along the bottom edge of an informational card."""
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setRange(0, milliseconds)
        bar.setValue(milliseconds)
        bar.setFixedHeight(3)
        self.progress = bar
        self._content.setContentsMargins(18, 14, 18, 10)
        self._content.addWidget(bar)
        return bar

    def add_widget(self, widget: QWidget) -> None:
        self._content.addWidget(widget)

    def add_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        self._content.addLayout(layout)

    def finish(self) -> None:
        """Close the bottom margin when the card has no footer of its own."""
        self._content.setContentsMargins(18, 14, 18, 14)


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
    if QGuiApplication.platformName() != "cocoa":
        # Offscreen and minimal plugins hand back a winId that is not an NSView, and
        # reading it as one takes the process down rather than raising.
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


def bring_to_front(widget: QWidget) -> None:
    """Show a window and actually put it in front.

    Privacy Guardian is an agent app (LSUIElement) with no Dock icon, so macOS never
    makes it the active application on its own. raise_() alone leaves a newly opened
    window behind whatever the person was looking at, which reads as the menu bar item
    doing nothing at all.
    """
    widget.show()
    widget.raise_()
    widget.activateWindow()
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication

        application = NSApplication.sharedApplication()
        if hasattr(application, "activate"):
            application.activate()
        else:  # pragma: no cover - macOS 13 and earlier
            application.activateIgnoringOtherApps_(True)
    except Exception:
        logging.getLogger(__name__).debug("application activation unchanged")


# Every floating surface in the corner, oldest first. A surface that arrives while
# another is up stacks above it rather than landing on top of it: a card covering the
# buttons of the card underneath makes the one the person is trying to answer
# unanswerable, which is worse than showing nothing at all.
_STACK: list[QWidget] = []


def _alive(widget: QWidget) -> bool:
    try:
        return widget.isVisible()
    except RuntimeError:  # the C++ object is already gone
        return False


def _prune() -> None:
    for widget in list(_STACK):
        try:
            widget.isVisible()
        except RuntimeError:
            _STACK.remove(widget)


def register_surface(widget: QWidget) -> None:
    """Add a floating surface to the corner stack, if it is not already in it."""
    _prune()
    if widget not in _STACK:
        _STACK.append(widget)
        widget.destroyed.connect(lambda *_args: _prune())


def release_surface(widget: QWidget) -> None:
    """Take a surface out of the stack and close the gap it leaves behind."""
    _prune()
    if widget in _STACK:
        _STACK.remove(widget)
    restack()


def restack() -> None:
    """Re-place every surface still on screen, bottom-up, so none of them overlap."""
    _prune()
    for widget in list(_STACK):
        if _alive(widget):
            anchor_bottom_right(widget, getattr(widget, "stack_content", lambda: None)())


def _occupied(widget: QWidget, rect: QRect) -> int:
    """How far up from the bottom edge the surfaces below this one already reach.

    Only what is on the screen being placed into counts: surfaces on another display
    are not in the way, and treating them as though they were would push this one up
    into the middle of an empty screen.
    """
    total = 0
    for other in _STACK:
        if other is widget:
            break
        if _alive(other) and rect.intersects(other.frameGeometry()):
            total += other.height()
    return total


def anchor_bottom_right(widget: QWidget, content: QWidget | None = None) -> None:
    """Pin the window to the bottom-right of the usable screen area.

    Two things have to happen before the move, or the window lands partly off screen
    and underneath the Dock, which draws above an always-on-top tool window:

    * the layout has to be activated, because a word-wrapped label reports far too
      small a height until it has been laid out at its real width, and
    * the height has to be capped to the space actually available.

    The surface is then raised above whatever else is already in the corner instead of
    being dropped on top of it.
    """
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    screen = target_screen(widget)
    if screen is None:
        widget.adjustSize()
        return
    register_surface(widget)
    rect = screen.availableGeometry()
    taken = min(_occupied(widget, rect), max(0, rect.height() - 2 * SCREEN_MARGIN))
    wanted = (content or widget).sizeHint()
    width = min(max(wanted.width(), widget.minimumWidth()), rect.width())
    height = min(max(wanted.height(), widget.minimumHeight()), rect.height() - taken)
    widget.resize(width, height)
    widget.move(
        max(rect.left(), rect.right() - width + 1),
        max(rect.top(), rect.bottom() - taken - height + 1),
    )
    keep_above_dock(widget)
