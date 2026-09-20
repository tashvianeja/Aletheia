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


def is_dark(mode: str = "system") -> bool:
    return mode == "dark" or (
        mode == "system" and QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )


def palette(mode: str = "system") -> dict[str, str]:
    return DARK if is_dark(mode) else LIGHT


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
#cardHeadline {{ font-size: 15px; font-weight: 700; color: {c["ink"]}; }}
#cardBody {{ font-size: 13px; color: {c["body"]}; }}
#cardRow {{ font-size: 13px; color: {c["ink"]}; }}
#cardRowDetail {{ font-size: 12px; color: {c["body"]}; }}
#cardContext {{ font-size: 12px; color: {c["muted"]}; }}
#cardFooter {{ font-size: 11px; color: {c["faint"]}; }}
#cardGlyphWarn {{ font-size: 13px; color: {c["warn"]}; font-weight: 700; }}
#cardGlyphOk {{ font-size: 13px; color: {c["ok"]}; font-weight: 700; }}
#cardGlyphInfo {{ font-size: 13px; color: {c["faint"]}; font-weight: 700; }}
#cardLock {{ font-size: 14px; color: {c["accent"]}; }}
"""
    )
