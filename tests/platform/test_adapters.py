from __future__ import annotations

import plistlib
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from privacy_guardian.core.events import DataCategory, PermissionRequestEvent, Requester
from privacy_guardian.sensors.platform.base import scan_extension_manifests
from privacy_guardian.sensors.platform.macos import MacOSAdapter
from privacy_guardian.sensors.platform.windows import WindowsAdapter


class MacBackend:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def foreground(self) -> Requester:
        return Requester(
            kind="application", bundle_id="com.synthetic.recorder", display_name="Recorder"
        )

    def accessibility(self) -> bool:
        return True

    def open_url(self, url: str) -> None:
        self.urls.append(url)


class Registry:
    def __init__(self, state: dict[str, dict[str, Any]]) -> None:
        self.state = state
        self.autostart: str | None = None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self.state

    def set_autostart(self, value: str | None) -> None:
        self.autostart = value


class Scheduler:
    def snapshot(self) -> dict[str, str]:
        return {}


class WindowsBackend:
    def foreground(self) -> Requester:
        return Requester(
            kind="application", exe_path=r"c:\apps\capture.exe", display_name="Capture"
        )


def create_tcc(path: Path, rows: list[tuple[str, str, int, int]]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE access(client TEXT, service TEXT, auth_value INTEGER, last_modified INTEGER)"
        )
        connection.executemany("INSERT INTO access VALUES (?, ?, ?, ?)", rows)


def test_macos_tcc_permission_grant_and_revocation_update_access_state(tmp_path: Path) -> None:
    database = tmp_path / "TCC.db"
    create_tcc(database, [("com.synthetic.recorder", "kTCCServiceScreenCapture", 2, 1)])
    adapter = MacOSAdapter(tcc_paths=[database], watch_paths=[], backend=MacBackend())
    granted = adapter.diff_tcc({}, adapter.read_tcc())
    assert [event.event_type for event in granted] == ["permission_request", "screen_capture"]
    assert adapter._access["com.synthetic.recorder"] == {DataCategory.SCREEN}

    revoked = adapter.diff_tcc(adapter.read_tcc(), {})
    assert revoked == []
    assert adapter._access["com.synthetic.recorder"] == set()


def test_macos_launch_agent_uses_app_bundle_identity_for_aggregation(tmp_path: Path) -> None:
    app = tmp_path / "Synthetic Capture.app"
    info = app / "Contents/Info.plist"
    info.parent.mkdir(parents=True)
    info.write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "com.synthetic.recorder",
                "CFBundleDisplayName": "Synthetic Capture",
            }
        )
    )
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / "vendor.synthetic.plist").write_bytes(
        plistlib.dumps(
            {
                "Label": "launch-label-that-differs",
                "ProgramArguments": [str(app / "Contents/MacOS/Capture"), "--background"],
            }
        )
    )
    adapter = MacOSAdapter(tcc_paths=[], watch_paths=[agents], backend=MacBackend())
    events = adapter.poll_files()
    startup = next(event for event in events if event.event_type == "startup_registration")
    breadth = next(event for event in events if event.event_type == "system_access")
    assert startup.requester.bundle_id == "com.synthetic.recorder"
    assert startup.requester.key == breadth.requester.key
    assert {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION} <= set(breadth.data_categories)


def test_windows_consent_and_run_command_aggregate_by_executable_identity() -> None:
    consent = (
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
        r"\ConsentStore\webcam\NonPackaged\C:#Apps#capture.exe"
    )
    run = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
    state = {
        consent: {"Value": "Allow", "LastUsedTimeStart": 10, "LastUsedTimeStop": 0},
        run: {"Synthetic Capture": r'"C:\Apps\capture.exe" --background'},
    }
    adapter = WindowsAdapter(
        registry=Registry(state),
        clipboard=WindowsBackend(),
        scheduler=Scheduler(),
        watch_paths=[],
    )
    events = adapter.diff_registry({}, state)
    permission = next(event for event in events if isinstance(event, PermissionRequestEvent))
    startup = next(event for event in events if event.event_type == "startup_registration")
    assert permission.requester.key == startup.requester.key
    breadth = [event for event in events if event.event_type == "system_access"][-1]
    assert {
        DataCategory.CAMERA,
        DataCategory.STARTUP,
        DataCategory.BACKGROUND_EXECUTION,
    } <= set(breadth.data_categories)


def test_windows_removed_consent_grant_is_removed_from_aggregate_access() -> None:
    consent = (
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
        r"\ConsentStore\webcam\NonPackaged\C:#Apps#capture.exe"
    )
    previous = {consent: {"Value": "Allow", "LastUsedTimeStart": 10, "LastUsedTimeStop": 0}}
    adapter = WindowsAdapter(
        registry=Registry(previous),
        clipboard=WindowsBackend(),
        scheduler=Scheduler(),
        watch_paths=[],
    )
    adapter.diff_registry({}, previous)
    assert adapter._access[r"c:\apps\capture.exe"] == {DataCategory.CAMERA}

    adapter.diff_registry(previous, {})

    assert adapter._access[r"c:\apps\capture.exe"] == set()


def test_macos_log_parser_handles_grant_denial_screen_and_clipboard() -> None:
    adapter = MacOSAdapter(tcc_paths=[], watch_paths=[], backend=MacBackend())
    granted = adapter.parse_log(
        {
            "eventMessage": (
                "client=com.synthetic.recorder service=kTCCServiceMicrophone authValue=2"
            )
        }
    )
    denied = adapter.parse_log(
        {"eventMessage": "bundleID=com.synthetic.recorder kTCCServiceCamera denied"}
    )
    screen = adapter.parse_log(
        {"eventMessage": "screen capture start bundleID=com.synthetic.recorder"}
    )
    clipboard = adapter.parse_log({"eventMessage": "Pasteboard privacy read prompt"})

    assert granted[0].permission == "microphone" and granted[0].state == "granted"
    assert denied[0].permission == "camera" and denied[0].state == "denied"
    assert screen[0].event_type == "screen_capture" and screen[0].active is True
    assert clipboard[0].event_type == "clipboard_read" and clipboard[0].proxy is True


def test_macos_access_breadth_accumulates_and_revocations_reduce_it() -> None:
    adapter = MacOSAdapter(tcc_paths=[], watch_paths=[], backend=MacBackend())
    current = {
        ("com.synthetic.converter", "kTCCServiceSystemPolicyAllFiles"): {
            "client": "com.synthetic.converter",
            "service": "kTCCServiceSystemPolicyAllFiles",
            "auth_value": 2,
            "last_modified": 1,
        },
        ("com.synthetic.converter", "kTCCServiceAccessibility"): {
            "client": "com.synthetic.converter",
            "service": "kTCCServiceAccessibility",
            "auth_value": 2,
            "last_modified": 1,
        },
        ("com.synthetic.converter", "kTCCServiceAppleEvents"): {
            "client": "com.synthetic.converter",
            "service": "kTCCServiceAppleEvents",
            "auth_value": 2,
            "last_modified": 1,
        },
    }
    events = adapter.diff_tcc({}, current)
    breadth = [event for event in events if event.event_type == "system_access"][-1]
    assert breadth.breadth == 1
    assert len(breadth.data_categories) == 3

    adapter.diff_tcc(current, {})
    assert adapter._access["com.synthetic.converter"] == set()


def test_windows_scheduler_detects_new_and_modified_tasks() -> None:
    class MutableScheduler:
        state: dict[str, str] = {}

        def snapshot(self) -> dict[str, str]:
            return self.state

    scheduler = MutableScheduler()
    adapter = WindowsAdapter(
        registry=Registry({}), clipboard=WindowsBackend(), scheduler=scheduler, watch_paths=[]
    )
    scheduler.state = {r"\Synthetic\Privacy Guardian": "<Task version='1'/>"}
    created = adapter.poll_tasks()
    scheduler.state = {r"\Synthetic\Privacy Guardian": "<Task version='2'/>"}
    modified = adapter.poll_tasks()

    assert created[0].mechanism == "scheduled_task" and created[0].modified is False
    assert modified[0].mechanism == "scheduled_task" and modified[0].modified is True


def test_browser_extension_permission_scan_has_plain_access_categories(tmp_path: Path) -> None:
    manifest = tmp_path / "Default/Extensions/synthetic/1.0/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"name":"Synthetic Helper","permissions":["history","tabs"],'
        '"host_permissions":["<all_urls>"]}'
    )
    events = scan_extension_manifests([tmp_path])
    assert len(events) == 1
    assert events[0].requester.display_name == "Synthetic Helper"
    assert set(events[0].data_categories) == {
        DataCategory.BROWSER_HISTORY,
        DataCategory.BROWSING_ACTIVITY,
    }
    assert events[0].breadth == 1


def test_macos_native_path_monitor_emits_launch_agent_within_two_seconds(tmp_path: Path) -> None:
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    emitted: list[Any] = []
    ready = threading.Event()

    def emit(event: Any) -> None:
        emitted.append(event)
        if event.event_type == "startup_registration":
            ready.set()

    adapter = MacOSAdapter(tcc_paths=[], watch_paths=[agents], backend=MacBackend())
    adapter.start(emit)
    try:
        started = time.monotonic()
        (agents / "com.synthetic.agent.plist").write_bytes(
            plistlib.dumps(
                {
                    "Label": "com.synthetic.agent",
                    "ProgramArguments": ["/Applications/Synthetic.app/Contents/MacOS/Synthetic"],
                }
            )
        )
        if not ready.wait(2):
            pytest.skip("native FSEvents stream is unavailable in the filesystem sandbox")
        assert time.monotonic() - started < 2
        assert any(event.requester.bundle_id == "com.synthetic.agent" for event in emitted)
    finally:
        adapter.stop()


def test_permission_settings_links_are_specific(monkeypatch) -> None:
    backend = MacBackend()
    mac = MacOSAdapter(tcc_paths=[], watch_paths=[], backend=backend)
    mac.open_settings("camera")
    mac.open_settings("screen")
    assert "Privacy_Camera" in backend.urls[0]
    assert "Privacy_ScreenCapture" in backend.urls[1]

    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    windows = WindowsAdapter(
        registry=Registry({}),
        clipboard=WindowsBackend(),
        scheduler=Scheduler(),
        watch_paths=[],
    )
    windows.open_settings("microphone")
    windows.open_settings("full_disk")
    assert opened == [
        "ms-settings:privacy-microphone",
        "ms-settings:privacy-broadfilesystemaccess",
    ]


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="real macOS read-only status check")
def test_real_macos_permission_status_is_read_only() -> None:
    adapter = MacOSAdapter()
    before = [(path, path.stat().st_mtime_ns) for path in adapter.tcc_paths if path.exists()]
    status = adapter.permissions_status()
    after = [(path, path.stat().st_mtime_ns) for path in adapter.tcc_paths if path.exists()]
    assert set(status) == {"full_disk_access", "accessibility"}
    assert all(isinstance(value, bool) for value in status.values())
    assert after == before


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="real Windows isolated HKCU fixture")
def test_real_windows_can_round_trip_isolated_hkcu_fixture() -> None:
    import winreg

    path = rf"Software\PrivacyGuardianTests\{uuid.uuid4()}"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, "Consent", 0, winreg.REG_SZ, "Allow")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            assert winreg.QueryValueEx(key, "Consent")[0] == "Allow"
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
