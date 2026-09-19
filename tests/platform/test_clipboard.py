from __future__ import annotations

from typing import Any

import pytest

from privacy_guardian.core.events import ClipboardReadEvent, Requester
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
