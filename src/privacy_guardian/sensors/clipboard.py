from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from privacy_guardian.core.events import ClipboardReadEvent, DataCategory, Requester
from privacy_guardian.util.privacy import public_identity


class ClipboardMonitor:
    def __init__(
        self, backend: Any, pool: Any, emit: Any, allowlist: list[str] | None = None
    ) -> None:
        self.backend = backend
        self.pool = pool
        self.emit = emit
        self.allowlist = allowlist or []
        self.sequence = -1
        self._sequence_has_text = False
        self.writer_key = ""
        self.foreground_key = ""
        self.categories: list[DataCategory] = []
        self._task: asyncio.Task[None] | None = None
        self.listener: Any = None
        self.changed = asyncio.Event()

    async def tick(self) -> None:
        sequence, text = await asyncio.to_thread(self.backend.clipboard)
        new_content = sequence != self.sequence or (bool(text) and not self._sequence_has_text)
        if not new_content and not self.categories:
            return
        requester: Requester = await asyncio.to_thread(self.backend.foreground)
        if new_content:
            self.sequence = sequence
            self._sequence_has_text = bool(text)
            owner = (
                await asyncio.to_thread(self.backend.clipboard_owner)
                if hasattr(self.backend, "clipboard_owner")
                else None
            )
            self.writer_key = owner.key if owner else requester.key
            from privacy_guardian.analysis.worker import analyze_payload

            if text:
                result = await self.pool.run(analyze_payload, {"kind": "text", "text": text})
                self.categories = sorted({finding.category for finding in result.findings}, key=str)
            else:
                self.categories = []
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
            and public_identity(requester.key) not in self.allowlist
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
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=0.25)
                self.changed.clear()
            except TimeoutError:
                pass

    def start(self) -> None:
        import sys

        if sys.platform == "win32":
            from privacy_guardian.sensors.platform.windows.clipboard_listener import (
                ClipboardListener,
            )

            loop = asyncio.get_running_loop()

            def changed() -> None:
                loop.call_soon_threadsafe(self.changed.set)

            self.listener = ClipboardListener(changed)
            self.listener.start()
        self._task = asyncio.create_task(self._loop())

    def stop_now(self) -> None:
        """Drop the monitor from outside its own loop, used when the service is restarted."""
        if self.listener:
            with contextlib.suppress(Exception):
                self.listener.stop()
            self.listener = None
        if self._task:
            self._task.cancel()
            self._task = None

    async def stop(self) -> None:
        if self.listener:
            await asyncio.to_thread(self.listener.stop)
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
