from __future__ import annotations

import contextlib
import importlib
import ntpath
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Literal

from privacy_guardian.analysis.purpose import enrich_requester
from privacy_guardian.core.events import (
    DataCategory,
    PermissionRequestEvent,
    PrivacyEvent,
    Requester,
    ScreenCaptureEvent,
    StartupRegistrationEvent,
    SystemAccessEvent,
)
from privacy_guardian.sensors.platform.base import (
    PERMISSION_CATEGORIES,
    Emit,
    PlatformAdapter,
    scan_extension_manifests,
)

CONSENT_ROOT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
RUN_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Run"
CAPABILITIES = {
    "webcam": "camera",
    "microphone": "microphone",
    "location": "location",
    "contacts": "contacts",
    "appointments": "calendar",
    "phoneCall": "microphone",
    "userDataTasks": "calendar",
    "broadFileSystemAccess": "full_disk",
    "documentsLibrary": "files",
    "picturesLibrary": "photos",
    "videosLibrary": "files",
    "activity": "browser_history",
    "bluetoothSync": "bluetooth",
    "graphicsCaptureProgrammatic": "screen",
    "graphicsCaptureWithoutBorder": "screen",
    "appDiagnostics": "background",
}


class WindowsRegistry:
    def snapshot(self) -> dict[str, dict[str, Any]]:
        winreg = importlib.import_module("winreg")

        values: dict[str, dict[str, Any]] = {}

        def visit(root: Any, path: str, prefix: str, depth: int = 0) -> None:
            if depth > 5:
                return
            try:
                with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
                    item: dict[str, Any] = {}
                    index = 0
                    while True:
                        try:
                            name, value, _kind = winreg.EnumValue(key, index)
                            item[name] = value
                            index += 1
                        except OSError:
                            break
                    values[prefix + "\\" + path] = item
                    index = 0
                    while True:
                        try:
                            child = winreg.EnumKey(key, index)
                            visit(root, path + "\\" + child, prefix, depth + 1)
                            index += 1
                        except OSError:
                            break
            except OSError:
                return

        for name, root in (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
            visit(root, CONSENT_ROOT, name)
            for path in (
                RUN_ROOT,
                RUN_ROOT + "Once",
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce",
            ):
                visit(root, path, name)
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services"
            ) as root:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, name) as key:
                            kind = winreg.QueryValueEx(key, "Type")[0]
                            if int(kind) & 3:
                                image = winreg.QueryValueEx(key, "ImagePath")[0]
                                values["HKLM\\SYSTEM\\CurrentControlSet\\Services\\" + name] = {
                                    "Type": kind,
                                    "ImagePath": image,
                                }
                    except OSError:
                        continue
        except OSError:
            pass
        return values

    def wait_for_change(self, stop: threading.Event, timeout: float = 1.0) -> bool:
        winreg = importlib.import_module("winreg")

        import win32api
        import win32con
        import win32event

        events = []
        keys = []
        try:
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for path in (CONSENT_ROOT, RUN_ROOT, r"SYSTEM\CurrentControlSet\Services"):
                    try:
                        key = winreg.OpenKey(root, path, 0, winreg.KEY_NOTIFY)
                        event = win32event.CreateEvent(None, False, False, None)
                        win32api.RegNotifyChangeKeyValue(
                            int(key),
                            True,
                            win32con.REG_NOTIFY_CHANGE_NAME | win32con.REG_NOTIFY_CHANGE_LAST_SET,
                            event,
                            True,
                        )
                        events.append(event)
                        keys.append(key)
                    except OSError:
                        continue
            if not events:
                stop.wait(timeout)
                return False
            return bool(
                win32event.WaitForMultipleObjects(events, False, int(timeout * 1000))
                != win32event.WAIT_TIMEOUT
            )
        finally:
            for key in keys:
                key.Close()
            for event in events:
                event.Close()

    def set_autostart(self, command: str | None) -> None:
        winreg = importlib.import_module("winreg")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_ROOT) as key:
            if command:
                winreg.SetValueEx(key, "PrivacyGuardian", 0, winreg.REG_SZ, command)
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, "PrivacyGuardian")


class WindowsClipboard:
    def foreground(self) -> Requester:
        import psutil
        import win32gui
        import win32process

        _thread, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
        try:
            process = psutil.Process(pid)
            return Requester(
                kind="application", exe_path=process.exe(), display_name=Path(process.exe()).stem
            )
        except (psutil.Error, OSError):
            return Requester(kind="application")

    def clipboard(self) -> tuple[int, str]:
        import win32clipboard

        sequence = win32clipboard.GetClipboardSequenceNumber()
        if sequence == getattr(self, "_clipboard_count", -1):
            return int(sequence), ""
        self._clipboard_count = sequence
        text = ""
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                text = str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                win32clipboard.CloseClipboard()
        return int(sequence), text

    def clear_clipboard(self) -> None:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
        finally:
            win32clipboard.CloseClipboard()

    def cloud_sync(self) -> bool:
        winreg = importlib.import_module("winreg")

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Clipboard") as key:
                return bool(winreg.QueryValueEx(key, "EnableCloudClipboard")[0])
        except OSError:
            return False


class WindowsScheduler:
    def snapshot(self) -> dict[str, str]:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        result: dict[str, str] = {}
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()

            def visit(folder: Any) -> None:
                for task in folder.GetTasks(0):
                    result[str(task.Path)] = str(task.Xml)
                for child in folder.GetFolders(0):
                    visit(child)

            visit(service.GetFolder("\\"))
        finally:
            pythoncom.CoUninitialize()
        return result


class WindowsAdapter(PlatformAdapter):
    def __init__(
        self,
        registry: Any = None,
        clipboard: Any = None,
        scheduler: Any = None,
        watch_paths: list[Path] | None = None,
    ) -> None:
        self.registry = registry or WindowsRegistry()
        self.backend = clipboard or WindowsClipboard()
        self.scheduler = scheduler or WindowsScheduler()
        self.watch_paths = (
            watch_paths
            if watch_paths is not None
            else [
                Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup",
                Path(os.getenv("PROGRAMDATA", ""))
                / "Microsoft/Windows/Start Menu/Programs/Startup",
            ]
        )
        self._state: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, str] = {}
        self._files: dict[str, int] = {}
        self._stop = threading.Event()
        self._emit: Emit = lambda _event: None
        self._thread: threading.Thread | None = None
        self._latest: list[PrivacyEvent] = []
        self._access: dict[str, set[DataCategory]] = {}
        self._process_thread: threading.Thread | None = None
        self._foreground: Requester | None = None
        self._injected = registry is not None
        self._path_monitor: Any = None
        self._fs_changed = threading.Event()
        self._extensions: dict[str, str] = {}

    @staticmethod
    def command_executable(command: str) -> str:
        match = re.match(r'^\s*"([^"]+)"|^\s*(.+?\.exe)(?:\s|$)', command, re.I)
        return ntpath.normcase(
            (match.group(1) or match.group(2)) if match else command.strip().strip('"')
        )

    def diff_registry(
        self, previous: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]
    ) -> list[PrivacyEvent]:
        events: list[PrivacyEvent] = []
        for removed_path in previous.keys() - current.keys():
            parts = removed_path.split("\\")
            if "ConsentStore" in parts:
                index = parts.index("ConsentStore")
                if len(parts) > index + 2:
                    capability = CAPABILITIES.get(parts[index + 1])
                    app = "\\".join(parts[index + 2 :])
                    identity = (
                        ntpath.normcase(app.removeprefix("NonPackaged\\").replace("#", "\\"))
                        if app.startswith("NonPackaged")
                        else app
                    )
                    if capability:
                        self._access.setdefault(identity, set()).discard(
                            PERMISSION_CATEGORIES[capability]
                        )
            elif parts[-1] in {"Run", "RunOnce"}:
                for command in previous[removed_path].values():
                    identity = self.command_executable(str(command))
                    self._access.setdefault(identity, set()).difference_update(
                        {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION}
                    )
        for path, values in current.items():
            old = previous.get(path, {})
            if old == values:
                continue
            parts = path.split("\\")
            if "ConsentStore" in parts:
                index = parts.index("ConsentStore")
                if len(parts) < index + 3:
                    continue
                capability = parts[index + 1]
                permission = CAPABILITIES.get(capability)
                if not permission:
                    continue
                app = "\\".join(parts[index + 2 :])
                exe = app.removeprefix("NonPackaged\\").replace("#", "\\")
                requester = enrich_requester(
                    Requester(
                        kind="application",
                        exe_path=ntpath.normcase(exe) if app.startswith("NonPackaged") else "",
                        bundle_id="" if app.startswith("NonPackaged") else app,
                        display_name=exe.split("\\")[-1].removesuffix(".exe"),
                    )
                )
                category = PERMISSION_CATEGORIES[permission]
                active = int(values.get("LastUsedTimeStart", 0)) > int(
                    values.get("LastUsedTimeStop", 0)
                )
                state: Literal["requested", "granted", "denied", "active", "stopped"] = (
                    "active"
                    if active
                    else "granted"
                    if values.get("Value") == "Allow"
                    else "denied"
                    if values.get("Value") == "Deny"
                    else "stopped"
                )
                events.append(
                    PermissionRequestEvent(
                        source="os",
                        platform="windows",
                        requester=requester,
                        data_categories=[category],
                        permission=permission,
                        state=state,
                    )
                )
                if permission == "screen":
                    events.append(
                        ScreenCaptureEvent(
                            source="os",
                            platform="windows",
                            requester=requester,
                            data_categories=[category],
                            active=active,
                            first_grant=not old and values.get("Value") == "Allow",
                        )
                    )
                if state in {"denied", "stopped"}:
                    self._access.setdefault(requester.key, set()).discard(category)
                if state in {"granted", "active"}:
                    self._access.setdefault(requester.key, set()).add(category)
                    if category == DataCategory.FILES_BROAD:
                        events.append(self._breadth(requester))
            elif "Services" in parts and int(values.get("Type", 0)) & 3:
                requester = Requester(
                    kind="application",
                    exe_path=self.command_executable(str(values.get("ImagePath", ""))),
                    display_name=parts[-1],
                )
                events.append(
                    SystemAccessEvent(
                        source="os",
                        platform="windows",
                        requester=requester,
                        data_categories=[DataCategory.FILES_BROAD, DataCategory.AUTOMATION],
                        accesses=["kernel_driver"],
                        breadth=1.0,
                    )
                )
            elif parts[-1] in {"Run", "RunOnce"}:
                for removed_name in old.keys() - values.keys():
                    identity = self.command_executable(str(old[removed_name]))
                    self._access.setdefault(identity, set()).difference_update(
                        {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION}
                    )
                for name, command in values.items():
                    if old.get(name) == command:
                        continue
                    requester = enrich_requester(
                        Requester(
                            kind="application",
                            exe_path=self.command_executable(str(command)),
                            display_name=name,
                        )
                    )
                    self._access.setdefault(requester.key, set()).update(
                        {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION}
                    )
                    events.append(
                        StartupRegistrationEvent(
                            source="os",
                            platform="windows",
                            requester=requester,
                            data_categories=[
                                DataCategory.STARTUP,
                                DataCategory.BACKGROUND_EXECUTION,
                            ],
                            mechanism=parts[-1],
                            modified=name in old,
                        )
                    )
                    events.append(self._breadth(requester))
        return events

    def _breadth(self, requester: Requester) -> SystemAccessEvent:
        categories = sorted(self._access.get(requester.key, set()), key=str)
        return SystemAccessEvent(
            source="os",
            platform="windows",
            requester=requester,
            data_categories=categories,
            accesses=[str(category) for category in categories],
            breadth=min(1, len(categories) / 3),
        )

    def poll_registry(self) -> list[PrivacyEvent]:
        current = self.registry.snapshot()
        events = self.diff_registry(self._state, current)
        self._state = current
        return events

    def poll_tasks(self) -> list[PrivacyEvent]:
        current = self.scheduler.snapshot()
        events: list[PrivacyEvent] = []
        for name, definition in current.items():
            if self._tasks.get(name) == definition:
                continue
            requester = enrich_requester(
                Requester(kind="application", bundle_id=name, display_name=name.rsplit("\\", 1)[-1])
            )
            events.append(
                StartupRegistrationEvent(
                    source="os",
                    platform="windows",
                    requester=requester,
                    data_categories=[DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION],
                    mechanism="scheduled_task",
                    modified=name in self._tasks,
                )
            )
        self._tasks = current
        return events

    def _process_starts(self) -> None:
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            locator = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
            events = locator.ExecNotificationQuery("SELECT * FROM Win32_ProcessStartTrace")
            while not self._stop.is_set():
                try:
                    event = events.NextEvent(1000)
                    self._foreground = Requester(
                        kind="application", display_name=str(event.ProcessName)
                    )
                except Exception:
                    continue
            pythoncom.CoUninitialize()
        except ImportError:
            return

    def _loop(self) -> None:
        last_tasks = 0.0
        last_registry = 0.0
        while not self._stop.is_set():
            try:
                if hasattr(self.registry, "wait_for_change"):
                    changed = self.registry.wait_for_change(self._stop, 1.0)
                else:
                    self._stop.wait(0.5)
                    changed = True
                events = []
                if changed or time.monotonic() - last_registry >= 10:
                    events = self.poll_registry()
                    last_registry = time.monotonic()
                if time.monotonic() - last_tasks >= 5:
                    events.extend(self.poll_tasks())
                    last_tasks = time.monotonic()
                    base = Path(os.getenv("LOCALAPPDATA", ""))
                    roots = [
                        base / name
                        for name in (
                            "Google/Chrome/User Data",
                            "Microsoft/Edge/User Data",
                            "BraveSoftware/Brave-Browser/User Data",
                        )
                    ]
                    roots.append(Path(os.getenv("APPDATA", "")) / "Mozilla/Firefox/Profiles")
                    for extension in scan_extension_manifests(roots):
                        signature = extension.model_dump_json(exclude={"id", "ts"})
                        if self._extensions.get(extension.requester.key) != signature:
                            self._extensions[extension.requester.key] = signature
                            events.append(extension)
                for root in self.watch_paths:
                    if not root.exists():
                        continue
                    for path in root.iterdir():
                        mtime = path.stat().st_mtime_ns
                        if self._files.get(str(path)) != mtime:
                            events.append(
                                StartupRegistrationEvent(
                                    source="os",
                                    platform="windows",
                                    requester=enrich_requester(
                                        Requester(
                                            kind="application",
                                            display_name=path.stem,
                                            exe_path=str(path),
                                        )
                                    ),
                                    data_categories=[
                                        DataCategory.STARTUP,
                                        DataCategory.BACKGROUND_EXECUTION,
                                    ],
                                    mechanism="startup_folder",
                                    modified=str(path) in self._files,
                                )
                            )
                            self._files[str(path)] = mtime
                self._latest = events or self._latest
                for event in events:
                    self._emit(event)
            except Exception:
                self._stop.wait(0.5)

    def start(self, emit: Emit) -> None:
        self._emit = emit
        self._state = self.registry.snapshot()
        self.diff_registry({}, self._state)
        from privacy_guardian.sensors.filesystem import PathMonitor

        self._path_monitor = PathMonitor(self.watch_paths, self._fs_changed.set)
        self._path_monitor.start()
        try:
            self._tasks = self.scheduler.snapshot()
        except Exception:
            self._tasks = {}
        self._thread = threading.Thread(target=self._loop, daemon=True, name="guardian-windows")
        self._thread.start()
        if sys.platform == "win32" and not self._injected:
            self._process_thread = threading.Thread(
                target=self._process_starts, daemon=True, name="guardian-processes"
            )
            self._process_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._path_monitor:
            self._path_monitor.stop()
        if self._thread:
            self._thread.join(timeout=2)

    def permissions_status(self) -> dict[str, bool]:
        return {"registry_monitoring": True, "clipboard_proxy": True}

    def foreground_requester(self) -> Requester:
        return enrich_requester(self.backend.foreground())

    def snapshot(self) -> list[PrivacyEvent]:
        requester = self.foreground_requester()
        base = Path(os.getenv("LOCALAPPDATA", ""))
        roots = [
            base / name
            for name in (
                "Google/Chrome/User Data",
                "Microsoft/Edge/User Data",
                "BraveSoftware/Brave-Browser/User Data",
            )
        ]
        roots.append(Path(os.getenv("APPDATA", "")) / "Mozilla/Firefox/Profiles")
        return [
            event
            for event in self.diff_registry({}, self.registry.snapshot())
            if event.requester.key == requester.key
        ] + scan_extension_manifests(roots)

    def open_settings(self, permission: str) -> None:
        import webbrowser

        page = {
            "camera": "webcam",
            "microphone": "microphone",
            "location": "location",
            "contacts": "contacts",
            "calendar": "calendar",
            "screen": "screenshot",
            "full_disk": "broadfilesystemaccess",
            "files": "documents",
            "photos": "pictures",
            "bluetooth": "radios",
        }.get(permission, "general")
        webbrowser.open("ms-settings:privacy-" + page)

    def set_autostart(self, enabled: bool) -> None:
        command = f'"{sys.executable}"' + (
            "" if getattr(sys, "frozen", False) else " -m privacy_guardian"
        )
        self.registry.set_autostart(command if enabled else None)
