from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from typing import Any


class ClipboardListener:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.thread: threading.Thread | None = None
        self.window: Any = None
        self.owner: int = 0

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="guardian-clipboard-listener"
        )
        self.thread.start()

    def _run(self) -> None:
        import win32api
        import win32con
        import win32gui

        def procedure(window: Any, message: int, wparam: int, lparam: int) -> int:
            if message == 0x031D:
                self.owner = int(
                    importlib.import_module("ctypes").windll.user32.GetClipboardOwner()
                )
                self.callback()
                return 0
            if message == win32con.WM_CLOSE:
                importlib.import_module("ctypes").windll.user32.RemoveClipboardFormatListener(
                    window
                )
                win32gui.DestroyWindow(window)
                return 0
            if message == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return int(win32gui.DefWindowProc(window, message, wparam, lparam))

        klass = win32gui.WNDCLASS()
        klass.lpfnWndProc = procedure
        klass.lpszClassName = "AletheiaClipboard"
        klass.hInstance = win32api.GetModuleHandle(None)
        atom = win32gui.RegisterClass(klass)
        self.window = win32gui.CreateWindowEx(
            0, atom, "", 0, 0, 0, 0, 0, win32con.HWND_MESSAGE, 0, klass.hInstance, None
        )
        importlib.import_module("ctypes").windll.user32.AddClipboardFormatListener(self.window)
        win32gui.PumpMessages()

    def stop(self) -> None:
        if self.window:
            importlib.import_module("ctypes").windll.user32.PostMessageW(self.window, 0x0010, 0, 0)
        if self.thread:
            self.thread.join(timeout=2)
