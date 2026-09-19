from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class PathMonitor:
    def __init__(
        self,
        paths: list[Path],
        callback: Callable[[], None],
        path_filter: Callable[[Path], bool] | None = None,
    ) -> None:
        self.paths = paths
        self.callback = callback
        self.path_filter = path_filter
        self.observer: Any = None

    def start(self) -> None:
        callback = self.callback
        path_filter = self.path_filter

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event: FileSystemEvent) -> None:
                if event.event_type in {"created", "modified", "deleted", "moved"}:
                    source = Path(str(event.src_path))
                    destination = Path(str(getattr(event, "dest_path", "")))
                    if path_filter is None or path_filter(source) or path_filter(destination):
                        callback()

        self.observer = Observer()  # FSEvents on macOS, ReadDirectoryChangesW on Windows.
        for path in self.paths:
            if path.is_dir():
                self.observer.schedule(Handler(), str(path), recursive=True)
        self.observer.start()

    def stop(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)
