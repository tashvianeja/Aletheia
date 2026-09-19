from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from privacy_guardian.sensors.filesystem import PathMonitor
from privacy_guardian.sensors.hotkey import GlobalHotkey


def test_path_monitor_routes_relevant_changes_only(tmp_path: Path, monkeypatch) -> None:
    callbacks: list[str] = []
    captured: list[object] = []

    class Observer:
        def schedule(self, handler, path: str, recursive: bool) -> None:
            captured.extend([handler, path, recursive])

        def start(self) -> None:
            callbacks.append("started")

        def stop(self) -> None:
            callbacks.append("stopped")

        def join(self, timeout: int) -> None:
            callbacks.append(f"joined:{timeout}")

    monkeypatch.setattr("privacy_guardian.sensors.filesystem.Observer", Observer)
    monitor = PathMonitor([tmp_path], lambda: callbacks.append("changed"))
    monitor.start()
    handler = captured[0]
    handler.on_any_event(SimpleNamespace(event_type="opened"))
    handler.on_any_event(SimpleNamespace(event_type="modified"))
    monitor.stop()

    assert captured[1:] == [str(tmp_path), True]
    assert callbacks == ["started", "changed", "stopped", "joined:2"]


def test_global_hotkey_is_safe_noop_on_unsupported_platform(monkeypatch) -> None:
    invoked: list[bool] = []
    monkeypatch.setattr("privacy_guardian.sensors.hotkey.sys.platform", "linux")
    hotkey = GlobalHotkey("Ctrl+Shift+P", lambda: invoked.append(True))
    hotkey.start()
    hotkey.stop()
    assert invoked == []
    assert hotkey._thread is None


def test_macos_hotkey_callback_matches_key_and_modifiers(monkeypatch) -> None:
    invoked: list[bool] = []
    handlers: list[object] = []
    removed: list[object] = []

    class EventApi:
        @staticmethod
        def addGlobalMonitorForEventsMatchingMask_handler_(_mask, handler):
            handlers.append(handler)
            return "monitor-token"

        @staticmethod
        def removeMonitor_(monitor) -> None:
            removed.append(monitor)

    appkit = SimpleNamespace(
        NSEvent=EventApi,
        NSEventMaskKeyDown=10,
        NSEventModifierFlagCommand=1,
        NSEventModifierFlagControl=2,
        NSEventModifierFlagOption=4,
        NSEventModifierFlagShift=8,
    )
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setattr("privacy_guardian.sensors.hotkey.sys.platform", "darwin")
    hotkey = GlobalHotkey("Cmd+Shift+P", lambda: invoked.append(True))
    hotkey.start()
    event = SimpleNamespace(modifierFlags=lambda: 1 | 8, charactersIgnoringModifiers=lambda: "p")
    handlers[0](event)
    hotkey.stop()
    assert invoked == [True]
    assert removed == ["monitor-token"]
