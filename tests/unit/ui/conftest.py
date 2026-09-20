from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from privacy_guardian.config import Settings
from privacy_guardian.engine.preferences import LearnedRules, UserPreferences
from privacy_guardian.storage import Store


class FakeHotkey:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeAdapter:
    def __init__(self) -> None:
        self.autostart: list[bool] = []
        self.opened: list[str] = []

    def set_autostart(self, enabled: bool) -> None:
        self.autostart.append(enabled)

    def open_settings(self, permission: str) -> None:
        self.opened.append(permission)


class UiController:
    def __init__(self, root: Path) -> None:
        self.settings = Settings(data_dir=root, onboarding_complete=True)
        self.core = SimpleNamespace(
            store=Store(root / "guardian.sqlite3"),
            preferences=UserPreferences(),
            learned_rules=LearnedRules(),
            adapter=FakeAdapter(),
            actions={},
            # What the browser is showing right now, as its heartbeat reports it.
            active_origin="",
            focused_origin="",
        )
        self.clipboard = SimpleNamespace(allowlist=[])
        self.hotkey = FakeHotkey()
        self.bridge = SimpleNamespace(deep_check_requested=SimpleNamespace(emit=lambda: None))
        self.calls: list[tuple[Any, ...]] = []
        # Setup state the onboarding walkthrough reads back.
        self.browsers: list[str] = []
        self.bridge_result: tuple[bool, str] = (True, "Browser bridge registered for chrome.")

    def diagnostics(self) -> dict[str, Any]:
        return {
            "version": "0.1.0",
            "database_counts": self.core.store.diagnostics(),
            "permissions": {"full_disk_access": False},
        }

    def submit_response(self, event_id: str, action: str, remember: bool) -> None:
        self.calls.append(("response", event_id, action, remember))

    def deep_check(self) -> None:
        self.calls.append(("deep_check",))

    def test_llm_connection(self, key: str, model: str) -> None:
        self.calls.append(("test_llm", key, model))

    def pause(self, seconds: int) -> None:
        self.calls.append(("pause", seconds))

    def show_dashboard(self, tab: str = "history") -> None:
        self.calls.append(("dashboard", tab))

    def show_report_window(self, report: dict[str, Any]) -> None:
        self.calls.append(("report", report))

    def show_permissions(self) -> None:
        self.calls.append(("permissions",))

    def show_extensions(self) -> None:
        self.calls.append(("extensions",))

    def show_onboarding(self) -> None:
        self.calls.append(("onboarding",))

    def check_updates(self) -> None:
        self.calls.append(("updates",))

    def quit(self) -> None:
        self.calls.append(("quit",))

    def permissions_status(self) -> dict[str, bool]:
        return {"full_disk_access": False, "accessibility": True}

    def open_settings(self, permission: str) -> None:
        self.calls.append(("open_settings", permission))

    def open_extension_folder(self) -> None:
        self.calls.append(("extension_folder",))

    def extension_folder(self) -> Path:
        return self.settings.data_dir / "extension"

    def connected_browsers(self) -> list[str]:
        return list(self.browsers)

    def register_bridge(self) -> tuple[bool, str]:
        self.calls.append(("register_bridge",))
        return self.bridge_result


@pytest.fixture
def ui_controller(tmp_path: Path) -> UiController:
    controller = UiController(tmp_path)
    yield controller
    controller.core.store.close()
