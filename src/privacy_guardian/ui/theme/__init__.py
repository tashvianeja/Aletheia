from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


def stylesheet(mode: str = "system") -> str:
    dark = mode == "dark" or (
        mode == "system" and QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )
    bg, fg, border, button = (
        ("#202329", "#f4f5f7", "#637083", "#354052")
        if dark
        else ("#ffffff", "#182230", "#697586", "#e7edf5")
    )
    return f"QWidget {{ background: {bg}; color: {fg}; font-size: 13px; }} QPushButton {{ background: {button}; border: 1px solid {border}; border-radius: 5px; padding: 7px 10px; }} QPushButton:focus {{ border: 2px solid #3378cd; }} QLineEdit,QSpinBox,QComboBox {{ border: 1px solid {border}; padding: 5px; }} QGroupBox {{ border: 1px solid {border}; margin-top: 14px; padding: 10px; }}"
