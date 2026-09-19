"""Render the real Qt widgets used for documentation screenshots."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from privacy_guardian.config import Settings
from privacy_guardian.core.events import (
    DataCategory,
    Decision,
    Outcome,
    PrivacyEvent,
    Requester,
)
from privacy_guardian.engine.preferences import LearnedRules, UserPreferences
from privacy_guardian.storage import Store
from privacy_guardian.ui.dashboard import Dashboard
from privacy_guardian.ui.deepcheck import DeepCheckWindow
from privacy_guardian.ui.onboarding import Onboarding
from privacy_guardian.ui.popup import InterventionPopup


class ScreenshotController:
    def __init__(self, data_dir: Path) -> None:
        self.settings = Settings(data_dir=data_dir, onboarding_complete=True)
        self.core = SimpleNamespace(
            store=Store(data_dir / "screenshots.sqlite3"),
            preferences=UserPreferences(),
            learned_rules=LearnedRules(),
            adapter=None,
            actions={},
        )
        self.clipboard = None

    def diagnostics(self):
        return {
            "version": "0.1.0",
            "permissions": {"full_disk_access": False, "accessibility": True},
            "database_counts": self.core.store.diagnostics(),
        }

    def permissions_status(self):
        return {"full_disk_access": False, "accessibility": True}

    def open_settings(self, _permission: str) -> None:
        pass

    def open_extension_folder(self) -> None:
        pass

    def show_dashboard(self) -> None:
        pass


def capture(widget, path: Path, app: QApplication) -> None:
    widget.show()
    app.processEvents()
    widget.grab().save(str(path), "PNG")
    widget.hide()


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Arial", 13))
    root = Path(__file__).parents[3]
    output = root / "docs/img"
    output.mkdir(parents=True, exist_ok=True)
    data_dir = Path(os.environ.get("SCREENSHOT_DATA_DIR", "/tmp/privacy-guardian-screenshots"))
    data_dir.mkdir(parents=True, exist_ok=True)
    database = data_dir / "screenshots.sqlite3"
    if database.exists():
        database.unlink()
    controller = ScreenshotController(data_dir)

    event = PrivacyEvent(
        id="screenshot-event",
        requester=Requester(
            origin="https://image-compressor.example", display_name="Image Compressor"
        ),
        data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT, DataCategory.BIOMETRIC_PHOTO],
    )
    controller.core.store.save_event(event)
    controller.core.store.save_decision(
        Decision(
            event_id=event.id,
            outcome=Outcome.INTERVENE,
            risk=0.94,
            explanation="This file contains identity information that an image compressor does not need.",
            rationale=[
                "A passport number and portrait were detected locally.",
                "The destination appears to provide image compression.",
            ],
            actions=["cancel", "continue", "redact"],
            default_action="cancel",
        )
    )
    popup = InterventionPopup(
        Decision(
            event_id=event.id,
            outcome=Outcome.INTERVENE,
            risk=0.94,
            explanation="This file contains identity information that an image compressor does not need.",
            rationale=["Passport details are unnecessary for image compression."],
            actions=["cancel", "continue", "redact"],
            default_action="cancel",
        )
    )
    popup.why_button.setChecked(True)
    capture(popup, output / "intervention-popup.png", app)

    dashboard = Dashboard(controller)
    dashboard.timer.stop()
    dashboard.resize(1000, 650)
    dashboard.history.setColumnWidth(0, 150)
    dashboard.history.setColumnWidth(1, 220)
    dashboard.history.setColumnWidth(2, 320)
    capture(dashboard, output / "dashboard.png", app)

    onboarding = Onboarding(controller)
    onboarding.timer.stop()
    onboarding.setStartId(1)
    capture(onboarding, output / "onboarding.png", app)

    deepcheck = DeepCheckWindow(controller)
    deepcheck.show_report(
        {
            "summary": "2 things to review",
            "findings": [
                {"summary": "This site appears to build an advertising profile."},
                {"summary": "Uploaded data may be retained after account deletion."},
            ],
            "checked": [
                {"kind": "permissions_checked", "available": True, "clean": True},
                {"kind": "screen", "available": True, "clean": True},
            ],
            "context_available": True,
        }
    )
    capture(deepcheck, output / "deep-check.png", app)
    controller.core.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
