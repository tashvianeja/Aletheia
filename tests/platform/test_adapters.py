from __future__ import annotations

import contextlib
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from privacy_guardian.core.events import DataCategory, PermissionRequestEvent, Requester
from privacy_guardian.engine.decision import decide
from privacy_guardian.sensors.platform.base import scan_extension_manifests
from privacy_guardian.sensors.platform.macos import MacOSAdapter
from privacy_guardian.sensors.platform.windows import WindowsAdapter, WindowsRegistry


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
    executable = r"c:\apps\capture.exe"
    adapter._access[executable] = {DataCategory.CAMERA}
    first_definition = (
        r"<Task version='1'><Actions><Exec><Command>C:\Apps\capture.exe</Command>"
        r"</Exec></Actions></Task>"
    )
    second_definition = first_definition.replace("version='1'", "version='2'")
    scheduler.state = {r"\Synthetic\Privacy Guardian": first_definition}
    created = adapter.poll_tasks()
    scheduler.state = {r"\Synthetic\Privacy Guardian": second_definition}
    modified = adapter.poll_tasks()

    assert created[0].mechanism == "scheduled_task" and created[0].modified is False
    assert created[0].requester.exe_path == executable
    assert set(created[1].data_categories) == {
        DataCategory.CAMERA,
        DataCategory.STARTUP,
        DataCategory.BACKGROUND_EXECUTION,
    }
    assert created[1].breadth == 1
    assert modified[0].mechanism == "scheduled_task" and modified[0].modified is True

    scheduler.state = {}
    assert adapter.poll_tasks() == []
    assert adapter._access[executable] == {DataCategory.CAMERA}


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


@pytest.mark.macos
@pytest.mark.platform
@pytest.mark.skipif(
    os.getenv("PRIVACY_GUARDIAN_NATIVE_WATCH_TEST") != "1",
    reason="set PRIVACY_GUARDIAN_NATIVE_WATCH_TEST=1 outside a filesystem sandbox",
)
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
    script = """
import json
from privacy_guardian.sensors.platform.macos import MacOSAdapter
adapter = MacOSAdapter()
before = [(str(path), path.stat().st_mtime_ns) for path in adapter.tcc_paths if path.exists()]
status = adapter.permissions_status()
after = [(str(path), path.stat().st_mtime_ns) for path in adapter.tcc_paths if path.exists()]
print(json.dumps({'before': before, 'status': status, 'after': after}))
"""
    process = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=10, check=True
    )
    result = json.loads(process.stdout)
    status = result["status"]
    assert set(status) == {"full_disk_access", "accessibility"}
    assert all(isinstance(value, bool) for value in status.values())
    assert result["after"] == result["before"]


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="real Windows isolated HKCU fixture")
def test_real_windows_registry_camera_grant_reaches_engine_as_intervention(monkeypatch) -> None:
    import winreg

    import privacy_guardian.sensors.platform.windows as windows_platform

    base = r"Software\PrivacyGuardianTests"
    root = rf"{base}\{uuid.uuid4()}"
    consent_root = root + r"\ConsentStore"
    leaf = consent_root + r"\webcam\NonPackaged\C:#Apps#PDFConverter.exe"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base):
            base_existed = True
    except FileNotFoundError:
        base_existed = False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, leaf) as key:
            winreg.SetValueEx(key, "Value", 0, winreg.REG_SZ, "Allow")
            winreg.SetValueEx(key, "LastUsedTimeStart", 0, winreg.REG_QWORD, 10)
            winreg.SetValueEx(key, "LastUsedTimeStop", 0, winreg.REG_QWORD, 0)
        monkeypatch.setattr(windows_platform, "CONSENT_ROOT", consent_root)
        adapter = WindowsAdapter(
            registry=WindowsRegistry(),
            clipboard=WindowsBackend(),
            scheduler=Scheduler(),
            watch_paths=[],
        )

        events = adapter.poll_registry()
        permission = next(
            event
            for event in events
            if isinstance(event, PermissionRequestEvent)
            and event.requester.exe_path.endswith(r"\pdfconverter.exe")
        )
        decision = decide(permission)

        assert permission.permission == "camera"
        assert permission.state == "active"
        assert permission.data_categories == [DataCategory.CAMERA]
        assert decision.outcome.value == "INTERVENE"
    finally:
        for path in (
            leaf,
            consent_root + r"\webcam\NonPackaged",
            consent_root + r"\webcam",
            consent_root,
            root,
        ):
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        if not base_existed:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)


def test_system_agents_never_reach_the_person(tmp_path: Path) -> None:
    """The bug this guards: a wave of "loginwindow is asking for your accessibility
    control" toasts for macOS's own agents, none of which anyone can act on."""
    database = tmp_path / "TCC.db"
    create_tcc(
        database,
        [
            ("com.apple.CoreLocationAgent", "kTCCServiceAccessibility", 2, 1),
            ("com.apple.loginwindow", "kTCCServiceAccessibility", 2, 1),
            ("/usr/libexec/trustd", "kTCCServiceAccessibility", 2, 1),
            ("com.synthetic.recorder", "kTCCServiceAccessibility", 2, 1),
        ],
    )
    adapter = MacOSAdapter(tcc_paths=[database], watch_paths=[], backend=MacBackend())
    published: list[Any] = []
    adapter._emit = published.append

    for event in adapter.diff_tcc({}, adapter.read_tcc()):
        adapter._publish(event)

    assert {event.requester.key for event in published} == {"com.synthetic.recorder"}


def test_routine_authorisation_lookups_are_not_permission_requests() -> None:
    """macOS consults the authorisation table constantly; none of that is a request."""
    adapter = MacOSAdapter(tcc_paths=[], watch_paths=[], backend=MacBackend())

    lookups = [
        adapter.parse_log(
            {
                "eventMessage": "AUTHREQ_CTX: msgID=1, service=kTCCServiceAccessibility, "
                "preflight=yes, query=1, client=com.synthetic.helper"
            }
        ),
        adapter.parse_log(
            {
                "eventMessage": "-[TCCDAccessIdentity staticCode]: static code for: "
                "identifier com.synthetic.helper, service kTCCServiceAccessibility"
            }
        ),
        adapter.parse_log(
            {"eventMessage": "client=com.synthetic.helper service=kTCCServiceCamera"}
        ),
    ]

    assert lookups == [[], [], []]


def test_a_permission_already_held_is_not_reported_as_a_request() -> None:
    adapter = MacOSAdapter(tcc_paths=[], watch_paths=[], backend=MacBackend())
    adapter._access["com.synthetic.recorder"] = {DataCategory.ACCESSIBILITY}

    repeat = adapter.parse_log(
        {"eventMessage": "client=com.synthetic.recorder kTCCServiceAccessibility allow"}
    )
    fresh = adapter.parse_log(
        {"eventMessage": "client=com.synthetic.recorder kTCCServiceCamera allow"}
    )

    assert repeat == []
    assert fresh[0].permission == "camera"


def test_reading_the_whole_table_reports_standing_grants_not_fresh_requests(
    tmp_path: Path,
) -> None:
    database = tmp_path / "TCC.db"
    create_tcc(database, [("com.synthetic.recorder", "kTCCServiceCamera", 2, 1)])
    adapter = MacOSAdapter(tcc_paths=[database], watch_paths=[], backend=MacBackend())

    standing = adapter.diff_tcc({}, adapter.read_tcc(), standing=True)
    changed = adapter.diff_tcc({}, adapter.read_tcc())

    assert standing[0].existing is True
    assert changed[0].existing is False
    assert "already has access to your camera" in decide(standing[0]).headline
    assert "was given access to your camera" in decide(changed[0]).headline
