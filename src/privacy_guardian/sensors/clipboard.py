from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from privacy_guardian.core.events import ClipboardReadEvent, DataCategory, Requester


class ClipboardMonitor:
    def __init__(
        self, backend: Any, pool: Any, emit: Any, allowlist: list[str] | None = None
    ) -> None:
        self.backend = backend
        self.pool = pool
        self.emit = emit
        self.allowlist = allowlist or []
        self.sequence = -1
        self.writer_key = ""
        self.foreground_key = ""
        self.categories: list[DataCategory] = []
        self._task: asyncio.Task[None] | None = None
        self.listener: Any = None
        self.changed = asyncio.Event()

    async def tick(self) -> None:
        sequence, text = await asyncio.to_thread(self.backend.clipboard)
        requester: Requester = await asyncio.to_thread(self.backend.foreground)
        if sequence != self.sequence:
            self.sequence = sequence
            self.writer_key = requester.key
            from privacy_guardian.analysis.worker import analyze_payload

            result = await self.pool.run(analyze_payload, {"kind": "text", "text": text})
            self.categories = sorted({finding.category for finding in result.findings}, key=str)
            text = ""
            cloud = (
                bool(self.backend.cloud_sync()) if hasattr(self.backend, "cloud_sync") else False
            )
            if cloud and self.categories:
                self.emit(
                    ClipboardReadEvent(
                        requester=requester,
                        data_categories=self.categories,
                        writer_key=self.writer_key,
                        proxy=True,
                        cloud_sync=True,
                    )
                )
        if (
            requester.key != self.foreground_key
            and self.categories
            and requester.key != self.writer_key
            and requester.key not in self.allowlist
        ):
            cloud = (
                bool(self.backend.cloud_sync()) if hasattr(self.backend, "cloud_sync") else False
            )
            self.emit(
                ClipboardReadEvent(
                    requester=requester,
                    data_categories=self.categories,
                    writer_key=self.writer_key,
                    proxy=True,
                    cloud_sync=cloud,
                )
            )
        self.foreground_key = requester.key

    async def _loop(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.tick()
            await asyncio.sleep(0.25)

    def start(self) -> None:
        import sys

        if sys.platform == "win32":
            from privacy_guardian.sensors.platform.windows.clipboard_listener import (
                ClipboardListener,
            )

            loop = asyncio.get_running_loop()
            self.listener = ClipboardListener(lambda: loop.call_soon_threadsafe(self.changed.set))
            self.listener.start()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self.listener:
            await asyncio.to_thread(self.listener.stop)
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
