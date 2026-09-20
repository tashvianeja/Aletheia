from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

# Tokens sampled from the reference renders in mockups/out.
LIGHT: dict[str, str] = {
    "ink": "#111827",
    "body": "#4b5563",
    "muted": "#6b7280",
    "faint": "#9ca3af",
    "line": "#e5e7eb",
    "border": "#d1d5db",
    "surface": "#ffffff",
    "raised": "#ffffff",
    "canvas": "#f9fafb",
    "accent": "#3b5bdb",
    "accent_hover": "#3450c8",
    "accent_soft": "#eef1fd",
    "warn": "#d97706",
    "ok": "#059669",
    "shadow": "#00000026",
}

DARK: dict[str, str] = {
    "ink": "#f3f4f6",
    "body": "#d1d5db",
    "muted": "#9ca3af",
    "faint": "#8b93a1",
    "line": "#343a46",
    "border": "#454c5a",
    "surface": "#1c1f26",
    "raised": "#23272f",
    "canvas": "#16181d",
    "accent": "#7b8fee",
    "accent_hover": "#93a4f2",
    "accent_soft": "#242a3d",
    "warn": "#f0a12e",
    "ok": "#34c793",
    "shadow": "#00000066",
}


# One colour family per urgency tier, in the meanings people already carry around:
# red stops you, amber warns you, green reassures you, blue merely tells you.
#
#   band      the strip across the top of the card
#   band_ink  text and icon on that strip
#   band_dim  the origin and close control on that strip
#   accent    the tier's colour on white: row icons, the emphasised word
#   soft      the wash behind the list of findings
#   border    the card's own outline
#
# "act_now" is the only tier whose band is solid rather than tinted: it is the one
# register that has to be recognised from across the room.
URGENCY_LIGHT: dict[str, dict[str, str]] = {
    "act_now": {
        "band": "#b91c1c",
        "band_ink": "#ffffff",
        "band_dim": "#fecaca",
        "accent": "#b91c1c",
        "soft": "#fef2f2",
        "border": "#b91c1c",
        "pulse": "#ef4444",
    },
    "attention": {
        "band": "#fee2e2",
        "band_ink": "#991b1b",
        "band_dim": "#c04848",
        "accent": "#dc2626",
        "soft": "#fff5f5",
        "border": "#f3a5a5",
        "pulse": "#fca5a5",
    },
    "heads_up": {
        "band": "#fef3c7",
        "band_ink": "#92400e",
        "band_dim": "#b8742a",
        "accent": "#d97706",
        "soft": "#fffbeb",
        "border": "#f6d98a",
        "pulse": "#fde68a",
    },
    "all_clear": {
        "band": "#d1fae5",
        "band_ink": "#065f46",
        "band_dim": "#2f8a6c",
        "accent": "#059669",
        "soft": "#ecfdf5",
        "border": "#a7e5cb",
        "pulse": "#a7f3d0",
    },
    "note": {
        "band": "#e8ecfd",
        "band_ink": "#2f46b0",
        "band_dim": "#6b7fd1",
        "accent": "#3b5bdb",
        "soft": "#f4f6fe",
        "border": "#c3cdf5",
        "pulse": "#c7d2fe",
    },
}

URGENCY_DARK: dict[str, dict[str, str]] = {
    "act_now": {
        "band": "#b91c1c",
        "band_ink": "#ffffff",
        "band_dim": "#fecaca",
        "accent": "#f87171",
        "soft": "#2f1b1b",
        "border": "#ef4444",
        "pulse": "#ef4444",
    },
    "attention": {
        "band": "#3f1d1d",
        "band_ink": "#fca5a5",
        "band_dim": "#e07c7c",
        "accent": "#f87171",
        "soft": "#2a1a1a",
        "border": "#7f2a2a",
        "pulse": "#5a2626",
    },
    "heads_up": {
        "band": "#3d2e12",
        "band_ink": "#fcd34d",
        "band_dim": "#d9a441",
        "accent": "#f0a12e",
        "soft": "#2a2316",
        "border": "#7a5a1a",
        "pulse": "#54401a",
    },
    "all_clear": {
        "band": "#123527",
        "band_ink": "#6ee7b7",
        "band_dim": "#4fc39a",
        "accent": "#34c793",
        "soft": "#16261f",
        "border": "#1f6b4f",
        "pulse": "#1a4a37",
    },
    "note": {
        "band": "#242a3d",
        "band_ink": "#a5b4fc",
        "band_dim": "#8494e0",
        "accent": "#7b8fee",
        "soft": "#1f2331",
        "border": "#3d4a80",
        "pulse": "#323a5c",
    },
}

URGENCIES = tuple(URGENCY_LIGHT)


def is_dark(mode: str = "system") -> bool:
    return mode == "dark" or (
        mode == "system" and QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )


def palette(mode: str = "system") -> dict[str, str]:
    return DARK if is_dark(mode) else LIGHT


def urgency_palette(mode: str = "system", urgency: str = "note") -> dict[str, str]:
    table = URGENCY_DARK if is_dark(mode) else URGENCY_LIGHT
    return table.get(urgency, table["note"])


def stylesheet(mode: str = "system") -> str:
    """Base chrome for ordinary windows: dashboard, onboarding, dialogs."""
    c = palette(mode)
    return f"""
QWidget {{ background: {c["surface"]}; color: {c["ink"]}; font-size: 13px; }}
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 21px; font-weight: 700; color: {c["ink"]}; }}
QLabel[role="subtitle"] {{ font-size: 13px; color: {c["muted"]}; }}
QLabel[role="section"] {{ font-size: 14px; font-weight: 600; color: {c["ink"]}; }}
QLabel[role="column"] {{ font-size: 11px; font-weight: 600; color: {c["faint"]}; }}
QLabel[role="body"] {{ color: {c["body"]}; }}
QLabel[role="muted"] {{ color: {c["muted"]}; }}
QLabel[role="warn"] {{ color: {c["warn"]}; }}
QLabel[role="metric"] {{ font-size: 26px; font-weight: 700; color: {c["ink"]}; }}
QPushButton {{
  background: {c["surface"]}; color: {c["ink"]};
  border: 1px solid {c["border"]}; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ background: {c["canvas"]}; }}
QPushButton:focus {{ border: 2px solid {c["accent"]}; }}
QPushButton:disabled {{
  background: {c["canvas"]}; color: {c["faint"]}; border: 1px solid {c["line"]};
}}
QPushButton[tier="primary"] {{
  background: {c["accent"]}; color: #ffffff; border: 1px solid {c["accent"]}; font-weight: 600;
}}
QPushButton[tier="primary"]:hover {{ background: {c["accent_hover"]}; }}
QPushButton[tier="primary"]:disabled {{
  background: {c["line"]}; color: {c["faint"]}; border: 1px solid {c["line"]};
}}
QPushButton[tier="tertiary"] {{
  background: transparent; color: {c["muted"]}; border: none; padding: 7px 10px;
}}
QPushButton[tier="tertiary"]:hover {{ color: {c["ink"]}; }}
QPushButton[tier="link"] {{
  background: transparent; color: {c["faint"]}; border: none; padding: 0px;
  text-decoration: underline; font-size: 11px;
}}
QPushButton[tier="link"]:hover {{ color: {c["body"]}; }}
QPushButton[tier="nav"] {{
  background: transparent; color: {c["body"]}; border: none;
  border-radius: 7px; padding: 8px 12px; text-align: left;
}}
QPushButton[tier="nav"]:hover {{ background: {c["canvas"]}; }}
QPushButton[tier="nav"][selected="true"] {{
  background: {c["accent_soft"]}; color: {c["accent"]}; font-weight: 600;
}}
QPushButton[tier="icon"] {{
  background: transparent; border: none; color: {c["faint"]};
  padding: 0px; font-size: 15px;
}}
QPushButton[tier="icon"]:hover {{ color: {c["ink"]}; }}
QFrame[role="card"] {{
  background: {c["raised"]}; border: 1px solid {c["line"]}; border-radius: 12px;
}}
QFrame[role="divider"] {{ background: {c["line"]}; border: none; max-height: 1px; }}
QFrame[role="sidebar"] {{ background: {c["canvas"]}; border-right: 1px solid {c["line"]}; }}
QLineEdit, QSpinBox, QComboBox, QTextEdit {{
  background: {c["surface"]}; color: {c["ink"]};
  border: 1px solid {c["border"]}; border-radius: 7px; padding: 6px 8px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
  border: 1px solid {c["accent"]};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QTableWidget {{
  background: {c["surface"]}; border: none; gridline-color: transparent;
}}
QTableWidget::item {{ padding: 8px 4px; border-bottom: 1px solid {c["line"]}; }}
QTableWidget::item:selected {{ background: {c["accent_soft"]}; color: {c["ink"]}; }}
QHeaderView::section {{
  background: {c["surface"]}; color: {c["faint"]}; border: none;
  border-bottom: 1px solid {c["line"]}; padding: 6px 4px; font-size: 11px; font-weight: 600;
}}
QScrollArea {{ border: none; }}
QCheckBox {{ spacing: 8px; }}
QProgressBar {{
  background: {c["line"]}; border: none; border-radius: 2px; max-height: 3px; text-align: center;
}}
QProgressBar::chunk {{ background: {c["accent"]}; border-radius: 2px; }}
QGroupBox {{ border: 1px solid {c["line"]}; border-radius: 10px; margin-top: 14px; padding: 10px; }}
"""


def _urgency_rules(mode: str) -> str:
    """Per-tier card chrome, keyed off the card's `urgency` dynamic property."""
    rules = []
    for urgency in URGENCIES:
        u = urgency_palette(mode, urgency)
        width = 2 if urgency == "act_now" else 1
        rules.append(
            f"""
#guardianCard[urgency="{urgency}"] {{ border: {width}px solid {u["border"]}; }}
#guardianCard[urgency="{urgency}"] #cardBandLabel {{ color: {u["band_ink"]}; }}
#guardianCard[urgency="{urgency}"] #cardBandOrigin {{ color: {u["band_dim"]}; }}
#guardianCard[urgency="{urgency}"] #findingsBox {{
  background: {u["soft"]}; border: 1px solid {u["border"]}; border-radius: 9px;
}}
"""
        )
    return "".join(rules)


def card_stylesheet(mode: str = "system") -> str:
    """The floating widget: a white card that has to read on top of any page."""
    c = palette(mode)
    return (
        stylesheet(mode)
        + f"""
#guardianCard {{
  background: {c["raised"]}; border: 1px solid {c["line"]}; border-radius: 14px;
}}
#guardianCard QLabel {{ background: transparent; }}
#cardTitle {{ font-size: 13px; font-weight: 700; color: {c["ink"]}; }}
#cardBandLabel {{ font-size: 12px; font-weight: 700; letter-spacing: 0.4px; }}
#cardBandOrigin {{ font-size: 11px; }}
#cardHeadline {{ font-size: 16px; font-weight: 700; color: {c["ink"]}; }}
#cardBody {{ font-size: 13px; color: {c["body"]}; }}
#cardRow {{ font-size: 13px; color: {c["ink"]}; }}
#cardRowDetail {{ font-size: 12px; color: {c["body"]}; }}
#cardContext {{ font-size: 12px; color: {c["muted"]}; }}
#cardContextStrong {{ font-size: 12px; font-weight: 600; color: {c["body"]}; }}
#cardFooter {{ font-size: 11px; color: {c["faint"]}; }}
#findingsBox {{ background: {c["canvas"]}; border: 1px solid {c["line"]}; border-radius: 9px; }}
#findingsBox QLabel {{ background: transparent; }}
#cardGlyphWarn {{ font-size: 13px; color: {c["warn"]}; font-weight: 700; }}
#cardGlyphOk {{ font-size: 13px; color: {c["ok"]}; font-weight: 700; }}
#cardGlyphInfo {{ font-size: 13px; color: {c["faint"]}; font-weight: 700; }}
#cardLock {{ font-size: 14px; color: {c["accent"]}; }}
QPushButton[tier="tertiary"] {{ text-decoration: underline; }}
"""
        + _urgency_rules(mode)
    )
