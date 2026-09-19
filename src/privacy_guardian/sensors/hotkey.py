from __future__ import annotations

import ctypes
import importlib
import sys
import threading
from collections.abc import Callable
from typing import Any


class GlobalHotkey:
    def __init__(self, shortcut: str, callback: Callable[[], None]) -> None:
        self.shortcut = shortcut
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._monitor: Any = None
        self._thread_id = 0

    def start(self) -> None:
        if sys.platform == "darwin":
            from AppKit import (
                NSEvent,
                NSEventMaskKeyDown,
                NSEventModifierFlagCommand,
                NSEventModifierFlagControl,
                NSEventModifierFlagOption,
                NSEventModifierFlagShift,
            )

            parts = self.shortcut.lower().split("+")
            required = 0
            for token in parts[:-1]:
                required |= {
                    "ctrl": NSEventModifierFlagCommand,
                    "cmd": NSEventModifierFlagCommand,
                    "meta": NSEventModifierFlagCommand,
                    "win": NSEventModifierFlagCommand,
                    "option": NSEventModifierFlagOption,
                    "control": NSEventModifierFlagControl,
                    "shift": NSEventModifierFlagShift,
                    "alt": NSEventModifierFlagOption,
                }.get(token, 0)

            def event_handler(event: Any) -> None:
                flags = int(event.modifierFlags())
                if (
                    str(event.charactersIgnoringModifiers() or "").lower() == parts[-1]
                    and flags & required == required
                ):
                    self.callback()

            self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown, event_handler
            )
        elif sys.platform == "win32":
            self._thread = threading.Thread(
                target=self._windows_loop, daemon=True, name="guardian-hotkey"
            )
            self._thread.start()

    def _windows_loop(self) -> None:
        from ctypes import wintypes

        user32 = importlib.import_module("ctypes").windll.user32
        self._thread_id = int(
            importlib.import_module("ctypes").windll.kernel32.GetCurrentThreadId()
        )
        parts = self.shortcut.lower().split("+")
        modifiers = 0x4000
        for token in parts[:-1]:
            modifiers |= {
                "ctrl": 2,
                "control": 2,
                "alt": 1,
                "option": 1,
                "shift": 4,
                "win": 8,
                "cmd": 8,
                "meta": 8,
            }.get(token, 0)
        key = ord(parts[-1].upper()) if len(parts[-1]) == 1 else 0x50
        if not user32.RegisterHotKey(None, 1, modifiers, key):
            return
        message = wintypes.MSG()
        try:
            while (
                not self._stop.is_set()
                and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0
            ):
                if message.message == 0x0312:
                    self.callback()
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        self._stop.set()
        if self._monitor is not None:
            from AppKit import NSEvent

            NSEvent.removeMonitor_(self._monitor)
        if sys.platform == "win32" and self._thread_id:
            importlib.import_module("ctypes").windll.user32.PostThreadMessageW(
                self._thread_id, 0x0012, 0, 0
            )
