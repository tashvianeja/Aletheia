from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from typing import Any

from aletheia.core.events import DataCategory, Requester
from aletheia.sensors.platform.windows import WindowsAdapter


class Registry:
    def __init__(self, state: dict[str, dict[str, Any]] | None = None) -> None:
        self.state = state or {}

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self.state

    def set_autostart(self, value: str | None) -> None:
        del value


class Clipboard:
    def foreground(self) -> Requester:
        return Requester(kind="application")


class Scheduler:
    def __init__(self) -> None:
        self.state: dict[str, str] = {}

    def snapshot(self) -> dict[str, str]:
        return self.state


def adapter(tmp_path: Path, scheduler: Scheduler | None = None) -> WindowsAdapter:
    return WindowsAdapter(
        registry=Registry(),
        clipboard=Clipboard(),
        scheduler=scheduler or Scheduler(),
        watch_paths=[tmp_path],
    )


def test_correlate_process_requires_recent_exact_executable_match(tmp_path: Path) -> None:
    sensor = adapter(tmp_path)
    now = time.monotonic()
    recent = Requester(
        kind="application",
        exe_path=r"C:\Apps\Bank Portal.exe",
        display_name="Online Banking",
    )
    process_key = WindowsAdapter.command_executable(recent.exe_path)
    sensor._recent_processes[process_key] = (now, recent)

    matched = sensor.correlate_process(
        Requester(kind="application", exe_path=r"c:\apps\BANK PORTAL.exe")
    )
    nearby = sensor.correlate_process(
        Requester(kind="application", exe_path=r"c:\apps\bank portal helper.exe")
    )
    sensor._recent_processes[process_key] = (now - 61, recent)
    expired = sensor.correlate_process(
        Requester(kind="application", exe_path=r"c:\apps\bank portal.exe")
    )

    assert matched.display_name == "Online Banking"
    assert matched.purpose == "banking"
    assert nearby.display_name == "Unknown requester"
    assert nearby.purpose == "unknown"
    assert expired.display_name == "Unknown requester"


def test_startup_requester_resolves_windows_shortcut_target(monkeypatch, tmp_path: Path) -> None:
    shortcut = tmp_path / "Synthetic Bank.lnk"
    shortcut.write_bytes(b"shortcut")
    calls: list[str] = []

    class Shell:
        def CreateShortcut(self, path: str):
            calls.append(path)
            return types.SimpleNamespace(TargetPath=r"C:\Apps\Bank Portal.exe")

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: calls.append("initialize")  # type: ignore[attr-defined]
    pythoncom.CoUninitialize = lambda: calls.append("uninitialize")  # type: ignore[attr-defined]
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda name: Shell()  # type: ignore[attr-defined]
    win32com = types.ModuleType("win32com")
    win32com.client = client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(sys, "platform", "win32")

    requester = adapter(tmp_path).startup_requester(shortcut)

    assert requester.exe_path == r"c:\apps\bank portal.exe"
    assert requester.display_name == "Synthetic Bank"
    assert calls == ["initialize", str(shortcut), "uninitialize"]


def test_startup_folder_emits_identity_and_system_access(tmp_path: Path) -> None:
    executable = tmp_path / "capture.exe"
    executable.write_bytes(b"synthetic")
    sensor = adapter(tmp_path)

    events = sensor.poll_startup_files()

    assert [event.event_type for event in events] == [
        "startup_registration",
        "system_access",
    ]
    assert events[0].requester.key == events[1].requester.key
    assert events[0].mechanism == "startup_folder"
    assert set(events[1].data_categories) == {
        DataCategory.STARTUP,
        DataCategory.BACKGROUND_EXECUTION,
    }
    assert sensor.poll_startup_files() == []


def test_startup_access_survives_until_all_folder_run_and_task_sources_are_removed(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "capture.exe"
    executable.write_bytes(b"synthetic")
    scheduler = Scheduler()
    sensor = adapter(tmp_path, scheduler)
    sensor.poll_startup_files()
    identity = sensor.startup_requester(executable).key
    run_key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
    run_state = {run_key: {"Capture": f'"{executable}" --background'}}
    sensor.diff_registry({}, run_state)
    sensor._state = run_state
    scheduler.state = {
        r"\Synthetic\Capture": (
            f"<Task><Actions><Exec><Command>{executable}</Command></Exec></Actions></Task>"
        )
    }
    sensor.poll_tasks()

    executable.unlink()
    sensor.poll_startup_files()
    assert DataCategory.STARTUP in sensor._access[identity]

    sensor.diff_registry(run_state, {})
    sensor._state = {}
    assert DataCategory.STARTUP in sensor._access[identity]

    scheduler.state = {}
    sensor.poll_tasks()
    assert sensor._access[identity].isdisjoint(
        {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION}
    )
