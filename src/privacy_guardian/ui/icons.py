from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Stroke-drawn glyphs so every icon stays crisp at menu-bar and widget sizes.
_PADLOCK = (
    '<path fill="none" stroke="{c}" stroke-width="1.7" stroke-linecap="round" '
    'd="M6.4 10.2V7.3a3.6 3.6 0 0 1 7.2 0v2.9"/>'
    '<rect x="4.2" y="10.2" width="11.6" height="8.1" rx="2.2" fill="none" '
    'stroke="{c}" stroke-width="1.7"/>'
)
_SHIELD = (
    '<path fill="none" stroke="{c}" stroke-width="1.5" stroke-linejoin="round" '
    'd="M10 2.6 16.4 5v5.1c0 4-3.8 6.4-6.4 7.6-2.6-1.2-6.4-3.6-6.4-7.6V5z"/>'
)
_WARNING = (
    '<path fill="{c}" d="M10 2.9 18.6 17H1.4z"/>'
    '<path fill="{i}" d="M9.1 7.3h1.8v5h-1.8zM9.1 13.6h1.8v1.8H9.1z"/>'
)
_TICK = (
    '<circle cx="10" cy="10" r="7.6" fill="{c}"/>'
    '<path fill="none" stroke="{i}" stroke-width="1.9" stroke-linecap="round" '
    'stroke-linejoin="round" d="m6.6 10.2 2.4 2.4 4.4-5"/>'
)
# A stop sign: the one shape that means "do not go on" without a word beside it.
_STOP = (
    '<path fill="{c}" d="M6.7 2.2h6.6l4.5 4.5v6.6l-4.5 4.5H6.7l-4.5-4.5V6.7z"/>'
    '<path fill="{i}" d="M9.1 5.9h1.8v5.4h-1.8zM9.1 12.7h1.8v1.8H9.1z"/>'
)
# An exclamation in a circle: worth a look, not a stop.
_ALERT = (
    '<circle cx="10" cy="10" r="7.6" fill="{c}"/>'
    '<path fill="{i}" d="M9.1 5.9h1.8v5.4h-1.8zM9.1 12.7h1.8v1.8H9.1z"/>'
)
# A lower-case i in a circle: a plain note.
_INFO_CIRCLE = (
    '<circle cx="10" cy="10" r="7.6" fill="{c}"/>'
    '<path fill="{i}" d="M9.1 8.8h1.8v5.4h-1.8zM9.1 5.8h1.8v1.8H9.1z"/>'
)
_DASH = '<rect x="4" y="9.2" width="12" height="1.7" rx="0.85" fill="{c}"/>'
_PENDING = '<circle cx="10" cy="10" r="6.4" fill="none" stroke="{c}" stroke-width="1.5"/>'
_SPINNER = (
    '<path fill="none" stroke="{c}" stroke-width="1.7" stroke-linecap="round" '
    'd="M10 3.6a6.4 6.4 0 1 0 6.4 6.4"/>'
)
_CLOSE = (
    '<path fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round" '
    'd="m5.8 5.8 8.4 8.4M14.2 5.8l-8.4 8.4"/>'
)
_ARROW = (
    '<path fill="none" stroke="{c}" stroke-width="1.4" stroke-linecap="round" '
    'stroke-linejoin="round" d="M4 10h11m-3.4-3.4L15 10l-3.4 3.4"/>'
)

GLYPHS = {
    "padlock": _PADLOCK,
    "shield": _SHIELD,
    "warn": _WARNING,
    "ok": _TICK,
    "stop": _STOP,
    "alert": _ALERT,
    "note": _INFO_CIRCLE,
    "info": _DASH,
    "pending": _PENDING,
    "running": _SPINNER,
    "close": _CLOSE,
    "arrow": _ARROW,
}


def svg(name: str, color: str, inner: str = "#ffffff") -> str:
    """The glyph in `color`; `inner` is the mark cut out of a filled shape."""
    body = GLYPHS[name].replace("{c}", color).replace("{i}", inner)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">{body}</svg>'


def pixmap(
    name: str, color: str, size: int = 16, ratio: float = 2.0, inner: str = "#ffffff"
) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg(name, color, inner).encode()))
    scaled = max(1, int(size * ratio))
    image = QPixmap(scaled, scaled)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, scaled, scaled))
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def icon(name: str, color: str, sizes: tuple[int, ...] = (16, 20, 24, 32, 48, 64)) -> QIcon:
    result = QIcon()
    for size in sizes:
        result.addPixmap(pixmap(name, color, size, ratio=1.0))
    return result
