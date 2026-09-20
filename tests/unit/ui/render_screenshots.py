"""Render the real Qt widgets used for documentation screenshots."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

from aletheia.config import Settings
from aletheia.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    FileUploadEvent,
    FormField,
    FormSubmitEvent,
    PrivacyEvent,
    Requester,
    TrackingEvent,
    UserResponse,
)
from aletheia.deepcheck import build_groups
from aletheia.engine.decision import decide
from aletheia.engine.preferences import LearnedRules, UserPreferences
from aletheia.storage import Store
from aletheia.ui.dashboard import Dashboard
from aletheia.ui.deepcheck import DeepCheckWindow
from aletheia.ui.onboarding import Onboarding
from aletheia.ui.popup import InterventionPopup


class ScreenshotController:
    def __init__(self, data_dir: Path) -> None:
        self.settings = Settings(data_dir=data_dir, onboarding_complete=True)
        self.core = SimpleNamespace(
            store=Store(data_dir / "screenshots.sqlite3"),
            preferences=UserPreferences(),
            learned_rules=LearnedRules(),
            adapter=None,
            actions={},
            connected_browsers={"chromium": 1.0},
            focused_origin="dropcrate.example",
        )
        self.clipboard = None

    def diagnostics(self) -> dict[str, Any]:
        return {
            "version": "0.1.0",
            "permissions": {"full_disk_access": False, "accessibility": True},
            "database_counts": self.core.store.diagnostics(),
        }

    def permissions_status(self) -> dict[str, bool]:
        return {"full_disk_access": False, "accessibility": True}

    def open_settings(self, _permission: str) -> None:
        pass

    def open_extension_folder(self) -> None:
        pass

    def show_dashboard(self, _section: str = "events") -> None:
        pass

    def show_report_window(self, _report: dict[str, Any]) -> None:
        pass

    def deep_check(self) -> None:
        pass

    def update_trackers(self) -> None:
        pass

    def check_updates(self) -> None:
        pass


def capture(widget: QWidget, path: Path, app: QApplication, fit: bool = True) -> None:
    widget.show()
    app.processEvents()
    if fit:
        # A floating card only knows its true height once its word-wrapped labels
        # have been laid out at the card's width; adjustSize() would clip it.
        content = getattr(widget, "stack_content", lambda: None)()
        if content is not None and content.layout() is not None:
            content.layout().activate()
            app.processEvents()
            widget.setFixedHeight(content.sizeHint().height())
        else:
            widget.adjustSize()
        app.processEvents()
    widget.grab().save(str(path), "PNG")
    widget.hide()


def _site(origin: str, purpose: str, name: str = "") -> Requester:
    return Requester(
        origin=origin,
        display_name=name or origin.split("//")[-1],
        purpose=purpose,
        purpose_confidence=0.9,
    )


def seed(controller: ScreenshotController) -> None:
    """A plausible day of history so the Events table is not empty."""
    now = datetime.now(UTC)
    samples: list[tuple[PrivacyEvent, str]] = [
        (
            ClipboardReadEvent(
                ts=now - timedelta(minutes=4),
                requester=Requester(
                    kind="application",
                    bundle_id="com.snippetly",
                    display_name="Snippetly",
                    purpose="productivity",
                    purpose_confidence=0.8,
                ),
                data_categories=[DataCategory.CREDENTIALS_PASSWORD],
                writer_key="other",
            ),
            "clear_clipboard",
        ),
        (
            ConsentBannerEvent(
                ts=now - timedelta(minutes=18),
                requester=_site("https://dailymeridian.example", "news"),
                purposes=["necessary", "analytics", "advertising"],
                dark_patterns=["buried_reject"],
                vendor_count=312,
            ),
            "reject_optional",
        ),
        (
            FileUploadEvent(
                ts=now - timedelta(hours=3),
                filename="passport.pdf",
                requester=_site("https://shrinkpix.example", "image_tool"),
                data_categories=[
                    DataCategory.GOVERNMENT_ID_PASSPORT,
                    DataCategory.FULL_NAME,
                    DataCategory.DOB,
                ],
            ),
            "redact",
        ),
        (
            FormSubmitEvent(
                ts=now - timedelta(days=1, hours=2),
                requester=_site("https://templatehive.example", "free_download"),
                fields=[
                    FormField(field_id="a", category=DataCategory.EMAIL, filled=True),
                    FormField(field_id="b", category=DataCategory.PHONE, filled=True),
                    FormField(field_id="c", category=DataCategory.DOB, filled=True),
                ],
            ),
            "review_fields",
        ),
    ]
    for event, action in samples:
        decision = decide(event)
        controller.core.store.save_event(event)
        controller.core.store.save_decision(decision)
        controller.core.store.save_response(UserResponse(event_id=event.id, action=action))
    # Quiet observations that never became a card, so the Overview tally has something
    # to count: trackers on the news site and the policy it was read against.
    tracking = TrackingEvent(
        ts=now - timedelta(minutes=19),
        requester=_site("https://dailymeridian.example", "news"),
        data_categories=[DataCategory.DEVICE_IDENTIFIERS],
        tracker_domains=["doubleclick.net", "scorecardresearch.com", "taboola.com"],
        fingerprinting=True,
        confidence=0.9,
    )
    controller.core.store.save_event(tracking)
    controller.core.store.save_decision(decide(tracking))
    controller.core.store.cache_document(
        "https://dailymeridian.example",
        "0" * 64,
        {"policy": {"missing": False, "clauses": []}, "word_counts": {"policy": 6900}},
    )


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Helvetica Neue", 13))
    root = Path(__file__).parents[3]
    output = root / "docs/img"
    output.mkdir(parents=True, exist_ok=True)
    data_dir = Path(os.environ.get("SCREENSHOT_DATA_DIR", "/tmp/aletheia-screenshots"))
    data_dir.mkdir(parents=True, exist_ok=True)
    database = data_dir / "screenshots.sqlite3"
    if database.exists():
        database.unlink()
    controller = ScreenshotController(data_dir)
    seed(controller)

    upload = FileUploadEvent(
        filename="passport.pdf",
        requester=_site("https://shrinkpix.example", "image_tool"),
        data_categories=[
            DataCategory.GOVERNMENT_ID_PASSPORT,
            DataCategory.FULL_NAME,
            DataCategory.DOB,
            DataCategory.BIOMETRIC_PHOTO,
        ],
    )
    capture(
        InterventionPopup(decide(upload), mode="light"),
        output / "intervention-popup.png",
        app,
    )

    dashboard = Dashboard(controller)
    dashboard.timer.stop()
    dashboard.resize(940, 620)
    capture(dashboard, output / "overview.png", app, fit=False)
    dashboard.select("events")
    capture(dashboard, output / "dashboard.png", app, fit=False)
    dashboard.select("settings")
    capture(dashboard, output / "settings.png", app, fit=False)

    onboarding = Onboarding(controller)
    onboarding.timer.stop()
    onboarding.setStartId(1)
    onboarding.resize(560, 400)
    capture(onboarding, output / "onboarding.png", app, fit=False)

    findings = [
        {
            "kind": "tracking",
            "severity": "INFORM",
            "summary": "Advertising profile",
            "detail": "Your activity may be used for personalised advertising.",
        },
        {
            "kind": "policy",
            "severity": "INFORM",
            "summary": "Data retention",
            "detail": "Uploaded files may be kept after you delete them.",
        },
    ]
    checked = [
        {"kind": "tracking", "available": True, "clean": False},
        {"kind": "policy", "available": True, "clean": False},
        {"kind": "forms", "available": True, "clean": True},
        {"kind": "permissions", "available": True, "clean": True},
    ]
    report = {
        "summary": "Overall: 2 things to review",
        "origin": "dropcrate.example",
        "ran_at": datetime.now(UTC).isoformat(),
        "findings": findings,
        "checked": checked,
        "groups": build_groups(findings, checked),
        "context_available": True,
    }
    deepcheck = DeepCheckWindow(controller, mode="light")
    deepcheck.show_report(report)
    capture(deepcheck, output / "deep-check.png", app)

    dashboard.show_report(report)
    capture(dashboard, output / "sites-and-apps.png", app, fit=False)
    controller.core.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
