"""Notice when a file we drew redaction boxes on is brought to the front, and offer the original back."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from aletheia.core.events import RedactedDocumentEvent

RESTORABLE = frozenset({".pdf", ".png"})
MAX_BYTES = 50 * 1024 * 1024


class OpenDocumentMonitor:
    """Polls the document under the frontmost window; one offer per file version."""

    def __init__(self, backend: Any, pool: Any, emit: Any) -> None:
        self.backend = backend
        self.pool = pool
        self.emit = emit
        self.current = ""
        self.seen: dict[str, int] = {}
        self._task: asyncio.Task[None] | None = None

    async def tick(self) -> None:
        if not hasattr(self.backend, "focused_document"):
            return
        path = str(await asyncio.to_thread(self.backend.focused_document) or "")
        if path == self.current:
            return
        self.current = path
        file = Path(path)
        if not path or file.suffix.lower() not in RESTORABLE:
            return
        try:
            stat = file.stat()
        except OSError:
            return
        if stat.st_size > MAX_BYTES or self.seen.get(path) == stat.st_mtime_ns:
            return
        self.seen[path] = stat.st_mtime_ns
        while len(self.seen) > 256:
            self.seen.pop(next(iter(self.seen)))
        from aletheia.analysis.worker import count_redaction_marks

        data = await asyncio.to_thread(file.read_bytes)
        marks = int(await self.pool.run(count_redaction_marks, data, file.name))
        if not marks:
            return
        requester = await asyncio.to_thread(self.backend.foreground)
        self.emit(
            RedactedDocumentEvent(requester=requester, path=path, filename=file.name, marks=marks)
        )

    async def _loop(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.tick()
            await asyncio.sleep(1.0)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop_now(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def stop(self) -> None:
        self.stop_now()
