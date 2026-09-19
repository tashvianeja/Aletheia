from __future__ import annotations

import os
import sys
import time
from typing import Any

import pytest

from privacy_guardian.core.events import ClipboardReadEvent, DataCategory, Requester
from privacy_guardian.core.pool import AnalysisPool
from privacy_guardian.sensors.clipboard import ClipboardMonitor


class InlinePool:
    async def run(self, function: Any, *args: Any) -> Any:
        return function(*args)


class ClipboardBackend:
    def __init__(self) -> None:
        self.sequence = 1
        self.text = "Synthetic account 4111111111111111"
        self.app = "writer.exe"
        self.sync = False

    def clipboard(self) -> tuple[int, str]:
        return self.sequence, self.text

    def foreground(self) -> Requester:
        return Requester(kind="application", exe_path=self.app, display_name=self.app)

    def cloud_sync(self) -> bool:
        return self.sync


@pytest.mark.asyncio
async def test_clipboard_warns_only_when_another_non_allowlisted_app_can_read() -> None:
    backend = ClipboardBackend()
    emitted: list[ClipboardReadEvent] = []
    monitor = ClipboardMonitor(backend, InlinePool(), emitted.append, allowlist=["safe.exe"])

    await monitor.tick()
    assert emitted == []
    assert monitor.categories

    backend.app = "safe.exe"
    await monitor.tick()
    assert emitted == []

    backend.app = "reader.exe"
    await monitor.tick()
    assert len(emitted) == 1
    assert emitted[0].requester.exe_path == "reader.exe"
    assert emitted[0].writer_key == "writer.exe"
    assert "4111111111111111" not in emitted[0].model_dump_json()


@pytest.mark.asyncio
async def test_clipboard_cloud_sync_warns_at_copy_time_without_raw_content() -> None:
    backend = ClipboardBackend()
    backend.sync = True
    emitted: list[ClipboardReadEvent] = []
    monitor = ClipboardMonitor(backend, InlinePool(), emitted.append)

    await monitor.tick()

    assert len(emitted) == 1
    assert emitted[0].cloud_sync is True
    assert emitted[0].writer_key == "writer.exe"
    assert "4111111111111111" not in repr(emitted)


@pytest.mark.asyncio
async def test_clipboard_sequence_change_replaces_prior_sensitive_categories() -> None:
    backend = ClipboardBackend()
    monitor = ClipboardMonitor(backend, InlinePool(), lambda _event: None)
    await monitor.tick()
    assert monitor.categories

    backend.sequence = 2
    backend.text = "ordinary non-sensitive text"
    await monitor.tick()

    assert monitor.categories == []


@pytest.mark.asyncio
@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="requires the native macOS pasteboard")
async def test_real_macos_clipboard_classifies_synthetic_card_within_500ms() -> None:
    from AppKit import NSPasteboard, NSPasteboardTypeString

    board = NSPasteboard.pasteboardWithUniqueName()

    class NativePasteboardBackend:
        def clipboard(self) -> tuple[int, str]:
            return int(board.changeCount()), str(board.stringForType_(NSPasteboardTypeString) or "")

        def foreground(self) -> Requester:
            return Requester(
                kind="application", bundle_id="test.synthetic.writer", display_name="Test writer"
            )

    pool = AnalysisPool(timeout=2)
    monitor = ClipboardMonitor(NativePasteboardBackend(), pool, lambda _event: None)
    try:
        started = time.perf_counter()
        board.clearContents()
        assert board.setString_forType_("Test card 4111111111111111", NSPasteboardTypeString)
        await monitor.tick()
        elapsed = time.perf_counter() - started
        print(f"real macOS clipboard classification latency: {elapsed:.6f}s")
        assert DataCategory.FINANCIAL_CARD_NUMBER in monitor.categories
        assert elapsed <= 0.5
    finally:
        await monitor.stop()
        pool.close()
        board.releaseGlobally()


@pytest.mark.asyncio
@pytest.mark.windows
@pytest.mark.skipif(
    sys.platform != "win32" or not os.getenv("CI"),
    reason="real global Windows clipboard test runs only on an isolated Windows CI desktop",
)
async def test_real_windows_clipboard_classifies_synthetic_card_within_500ms() -> None:
    import win32clipboard

    from privacy_guardian.sensors.platform.windows import WindowsClipboard

    previous = ""
    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            previous = str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
    finally:
        win32clipboard.CloseClipboard()
    pool = AnalysisPool(timeout=2)
    monitor = ClipboardMonitor(WindowsClipboard(), pool, lambda _event: None)
    try:
        started = time.perf_counter()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText("Test card 4111111111111111")
        finally:
            win32clipboard.CloseClipboard()
        await monitor.tick()
        elapsed = time.perf_counter() - started
        print(f"real Windows clipboard classification latency: {elapsed:.6f}s")
        assert DataCategory.FINANCIAL_CARD_NUMBER in monitor.categories
        assert elapsed <= 0.5
    finally:
        await monitor.stop()
        pool.close()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            if previous:
                win32clipboard.SetClipboardText(previous)
        finally:
            win32clipboard.CloseClipboard()
