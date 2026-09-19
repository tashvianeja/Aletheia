from __future__ import annotations

import json
import plistlib
import re
import sqlite3
import subprocess
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

TCC_PERMISSIONS = {
    "kTCCServiceCamera": "camera",
    "kTCCServiceMicrophone": "microphone",
    "kTCCServiceLocation": "location",
    "kTCCServiceAddressBook": "contacts",
    "kTCCServiceCalendar": "calendar",
    "kTCCServicePhotos": "photos",
    "kTCCServiceSystemPolicyDesktopFolder": "files",
    "kTCCServiceSystemPolicyDocumentsFolder": "files",
    "kTCCServiceSystemPolicyDownloadsFolder": "files",
    "kTCCServiceSystemPolicyRemovableVolumes": "files",
    "kTCCServiceSystemPolicyNetworkVolumes": "files",
    "kTCCServiceSystemPolicyAllFiles": "full_disk",
    "kTCCServiceAccessibility": "accessibility",
    "kTCCServiceScreenCapture": "screen",
    "kTCCServiceListenEvent": "input_monitoring",
    "kTCCServiceAppleEvents": "automation",
    "kTCCServicePostEvent": "automation",
    "kTCCServiceBluetoothAlways": "bluetooth",
    "kTCCServiceNotifications": "notifications",
}


class MacBackend:
    def foreground(self) -> Requester:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not app:
            return Requester(kind="application")
        return Requester(
            kind="application",
            bundle_id=str(app.bundleIdentifier() or ""),
            display_name=str(app.localizedName() or "Unknown application"),
            exe_path=str(app.executableURL().path() if app.executableURL() else ""),
        )

    def accessibility(self) -> bool:
        from Quartz import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())

    def open_url(self, url: str) -> None:
        from AppKit import NSWorkspace
        from Foundation import NSURL

        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def clipboard(self) -> tuple[int, str]:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        board = NSPasteboard.generalPasteboard()
        count = int(board.changeCount())
        if count == getattr(self, "_clipboard_count", -1) and not getattr(
            self, "_clipboard_empty", False
        ):
            return count, ""
        self._clipboard_count = count
        text = str(board.stringForType_(NSPasteboardTypeString) or "")
        # clearContents advances changeCount, while a subsequent setString can
        # reuse that count. Retry transient empty reads until content is available.
        self._clipboard_empty = not text
        return count, text

    def clear_clipboard(self) -> None:
        from AppKit import NSPasteboard

        NSPasteboard.generalPasteboard().clearContents()


class MacOSAdapter(PlatformAdapter):
    def __init__(
        self,
        tcc_paths: list[Path] | None = None,
        watch_paths: list[Path] | None = None,
        backend: Any = None,
    ) -> None:
        self.tcc_paths = (
            tcc_paths
            if tcc_paths is not None
            else [
                Path.home() / "Library/Application Support/com.apple.TCC/TCC.db",
                Path("/Library/Application Support/com.apple.TCC/TCC.db"),
            ]
        )
        self.watch_paths = (
            watch_paths
            if watch_paths is not None
            else [
                Path.home() / "Library/LaunchAgents",
                Path("/Library/LaunchAgents"),
                Path("/Library/LaunchDaemons"),
                Path.home() / "Library/Application Support/com.apple.backgroundtaskmanagementagent",
                Path("/var/db/com.apple.backgroundtaskmanagement"),
                Path("/Library/SystemExtensions"),
                Path("/Library/Extensions"),
            ]
        )
        self.backend = backend or MacBackend()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log_thread: threading.Thread | None = None
        self._log_process: subprocess.Popen[str] | None = None
        self._emit: Emit = lambda _event: None
        self._tcc: dict[tuple[str, str], dict[str, Any]] = {}
        self._files: dict[str, int] = {}
        self._background_items: dict[str, Requester] = {}
        self._background_changed = True
        self._latest: list[PrivacyEvent] = []
        self._access: dict[str, set[DataCategory]] = {}
        self._extension_state: dict[str, str] = {}
        self._path_monitor: Any = None
        self._extension_monitor: Any = None
        self._extensions_changed = threading.Event()
        self._fs_changed = threading.Event()
        self._startup_requesters: dict[str, Requester] = {}
        self._injected = backend is not None or tcc_paths is not None or watch_paths is not None

    def read_tcc(self) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for path in self.tcc_paths:
            try:
                with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.2) as connection:
                    connection.row_factory = sqlite3.Row
                    for row in connection.execute("SELECT * FROM access"):
                        value = dict(row)
                        result[(str(value["client"]), str(value["service"]))] = value
            except (sqlite3.Error, OSError):
                continue
        return result

    def diff_tcc(
        self,
        previous: dict[tuple[str, str], dict[str, Any]],
        current: dict[tuple[str, str], dict[str, Any]],
    ) -> list[PrivacyEvent]:
        events: list[PrivacyEvent] = []
        for removed_key in previous.keys() - current.keys():
            client, service = removed_key
            permission = TCC_PERMISSIONS.get(service)
            if permission:
                self._access.setdefault(client, set()).discard(PERMISSION_CATEGORIES[permission])
        for key, row in current.items():
            old = previous.get(key)
            auth = row.get("auth_value", row.get("allowed", 0))
            if (
                old
                and old.get("auth_value", old.get("allowed", 0)) == auth
                and old.get("last_modified") == row.get("last_modified")
            ):
                continue
            client, service = key
            permission = TCC_PERMISSIONS.get(service)
            if not permission:
                continue
            requester = enrich_requester(
                Requester(
                    kind="application",
                    bundle_id=client if not client.startswith("/") else "",
                    exe_path=client if client.startswith("/") else "",
                    display_name=Path(client).stem if "/" in client else client.split(".")[-1],
                )
            )
            category = PERMISSION_CATEGORIES[permission]
            state: Literal["requested", "granted", "denied", "active", "stopped"] = (
                "granted" if auth in (1, 2, 3) else "denied"
            )
            event = PermissionRequestEvent(
                source="os",
                platform="macos",
                requester=requester,
                data_categories=[category],
                permission=permission,
                state=state,
            )
            events.append(event)
            if permission == "screen" and state == "granted":
                events.append(
                    ScreenCaptureEvent(
                        source="os",
                        platform="macos",
                        requester=requester,
                        data_categories=[DataCategory.SCREEN],
                        first_grant=old is None,
                    )
                )
            if state == "denied":
                self._access.setdefault(requester.key, set()).discard(category)
            if state == "granted":
                self._access.setdefault(requester.key, set()).add(category)
                if category in {
                    DataCategory.FILES_BROAD,
                    DataCategory.ACCESSIBILITY,
                    DataCategory.AUTOMATION,
                }:
                    events.append(self._breadth(requester))
        return events

    def _breadth(self, requester: Requester) -> SystemAccessEvent:
        accesses = self._access.setdefault(requester.key, set())
        return SystemAccessEvent(
            source="os",
            platform="macos",
            requester=requester,
            data_categories=sorted(accesses, key=str),
            accesses=[str(category) for category in accesses],
            breadth=min(1, len(accesses) / 3),
        )

    def poll_tcc(self) -> list[PrivacyEvent]:
        current = self.read_tcc()
        events = self.diff_tcc(self._tcc, current)
        self._tcc = current
        return events

    def poll_files(self) -> list[PrivacyEvent]:
        current: dict[str, int] = {}
        events: list[PrivacyEvent] = []
        for root in self.watch_paths:
            if not root.exists():
                continue
            for path in root.iterdir():
                try:
                    current[str(path)] = path.stat().st_mtime_ns
                    if self._files.get(str(path)) == current[str(path)]:
                        continue
                    if path.suffix == ".btm":
                        self._background_changed = True
                        continue
                    label = path.stem
                    executable = ""
                    if path.suffix == ".plist":
                        info = plistlib.loads(path.read_bytes())
                        label = str(info.get("Label", label))
                        arguments = info.get("ProgramArguments", [])
                        executable = str(info.get("Program", arguments[0] if arguments else ""))
                    requester = enrich_requester(
                        Requester(
                            kind="application",
                            bundle_id=label,
                            exe_path=executable,
                            display_name=label,
                        )
                    )
                    normalized_executable = executable.replace("\\", "/")
                    if ".app/" in normalized_executable:
                        app_root = Path(normalized_executable.split(".app/", 1)[0] + ".app")
                        try:
                            app_info = plistlib.loads(
                                (app_root / "Contents/Info.plist").read_bytes()
                            )
                            requester.bundle_id = str(
                                app_info.get("CFBundleIdentifier", requester.bundle_id)
                            )
                            requester.display_name = str(
                                app_info.get(
                                    "CFBundleDisplayName",
                                    app_info.get("CFBundleName", requester.display_name),
                                )
                            )
                        except (OSError, ValueError):
                            pass
                    if root.name in {"SystemExtensions", "Extensions"}:
                        events.append(
                            SystemAccessEvent(
                                source="os",
                                platform="macos",
                                requester=requester,
                                data_categories=[DataCategory.FILES_BROAD, DataCategory.AUTOMATION],
                                accesses=["system_extension"],
                                breadth=1.0,
                            )
                        )
                        continue
                    self._startup_requesters[str(path)] = requester
                    self._access.setdefault(requester.key, set()).update(
                        {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION}
                    )
                    events.append(
                        StartupRegistrationEvent(
                            source="os",
                            platform="macos",
                            requester=requester,
                            data_categories=[
                                DataCategory.STARTUP,
                                DataCategory.BACKGROUND_EXECUTION,
                            ],
                            mechanism=root.name,
                            modified=str(path) in self._files,
                        )
                    )
                    events.append(self._breadth(requester))
                except (OSError, ValueError, plistlib.InvalidFileException):
                    continue
        for deleted in self._files.keys() - current.keys():
            removed_requester = self._startup_requesters.pop(deleted, None)
            if removed_requester:
                self._access.setdefault(removed_requester.key, set()).difference_update(
                    {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION}
                )
        self._files = current
        return events

    @staticmethod
    def parse_background_items(text: str) -> dict[str, Requester]:
        from urllib.parse import unquote, urlsplit

        result: dict[str, Requester] = {}
        # sfltool emits numbered item records with a UUID followed by public app metadata.
        for block in re.split(r"(?m)^\s*#\d+:|(?=^\s*UUID:)", text, flags=re.M):
            values = {
                key.strip().lower(): value.strip()
                for key, value in re.findall(r"(?m)^\s*([A-Za-z ]+):\s*(.+)$", block)
            }
            identifier = values.get("identifier", "")
            executable = values.get("executable path", values.get("url", ""))
            if executable.startswith("file:"):
                executable = unquote(urlsplit(executable).path)
            if not identifier and not executable:
                continue
            disposition = values.get("disposition", "").lower()
            if disposition and "enabled" not in disposition and "allowed" not in disposition:
                continue
            requester = enrich_requester(
                Requester(
                    kind="application",
                    bundle_id=identifier,
                    exe_path=executable,
                    display_name=values.get("name", identifier or Path(executable).name),
                )
            )
            result[requester.key] = requester
        return result

    def poll_background_items(self) -> list[PrivacyEvent]:
        if self._injected or sys.platform != "darwin":
            return []
        try:
            completed = subprocess.run(
                ["/usr/bin/sfltool", "dumpbtm"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if completed.returncode:
            return []
        current = self.parse_background_items(completed.stdout)
        startup = {DataCategory.STARTUP, DataCategory.BACKGROUND_EXECUTION}
        events: list[PrivacyEvent] = []
        for key in self._background_items.keys() - current.keys():
            self._access.setdefault(key, set()).difference_update(startup)
        for key, requester in current.items():
            self._access.setdefault(key, set()).update(startup)
            if key not in self._background_items:
                events.extend(
                    [
                        StartupRegistrationEvent(
                            source="os",
                            platform="macos",
                            requester=requester,
                            data_categories=sorted(startup, key=str),
                            mechanism="background_item",
                        ),
                        self._breadth(requester),
                    ]
                )
        self._background_items = current
        return events

    def parse_log(self, record: dict[str, Any]) -> list[PrivacyEvent]:
        message = str(record.get("eventMessage", ""))
        service_match = re.search(r"kTCCService[A-Za-z]+", message)
        client_match = re.search(
            r"(?:client|identifier|responsible|bundleID)\s*[=:]\s*[\"']?([A-Za-z0-9_.-]+)", message
        )
        if not service_match or not client_match:
            if re.search(r"screen.?captur|screen.?record", message, re.I) and client_match:
                requester = Requester(
                    kind="application",
                    bundle_id=client_match[1],
                    display_name=client_match[1].split(".")[-1],
                )
                active = bool(re.search(r"start|active|begin", message, re.I))
                return [
                    ScreenCaptureEvent(
                        source="os",
                        platform="macos",
                        requester=requester,
                        data_categories=[DataCategory.SCREEN],
                        active=active,
                    )
                ]
            if re.search(r"paste|clipboard", message, re.I) and re.search(
                r"privacy|prompt|read", message, re.I
            ):
                from privacy_guardian.core.events import ClipboardReadEvent

                requester = self.foreground_requester()
                return [
                    ClipboardReadEvent(
                        platform="macos",
                        requester=requester,
                        data_categories=[DataCategory.CLIPBOARD],
                        proxy=True,
                    )
                ]
            return []
        permission = TCC_PERMISSIONS.get(service_match[0])
        if not permission:
            return []
        requester = enrich_requester(
            Requester(
                kind="application",
                bundle_id=client_match[1],
                display_name=client_match[1].split(".")[-1],
            )
        )
        state: Literal["requested", "granted", "denied", "active", "stopped"] = (
            "denied"
            if re.search(r"deny|denied|authValue=0", message, re.I)
            else "granted"
            if re.search(r"grant|allow|authValue=2", message, re.I)
            else "requested"
        )
        return [
            PermissionRequestEvent(
                source="os",
                platform="macos",
                requester=requester,
                data_categories=[PERMISSION_CATEGORIES[permission]],
                permission=permission,
                state=state,
            )
        ]

    def _logs(self) -> None:
        try:
            self._log_process = subprocess.Popen(
                [
                    "/usr/bin/log",
                    "stream",
                    "--style",
                    "ndjson",
                    "--predicate",
                    'subsystem == "com.apple.TCC" OR subsystem == "com.apple.pasteboard"',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            assert self._log_process.stdout is not None
            for line in self._log_process.stdout:
                if self._stop.is_set():
                    break
                try:
                    for event in self.parse_log(json.loads(line)):
                        self._emit(event)
                except (ValueError, TypeError):
                    continue
        except OSError:
            return

    def _loop(self) -> None:
        last_tcc = 0.0
        last_extensions = 0.0
        while not self._stop.is_set():
            changed = self._fs_changed.wait(1.0)
            self._fs_changed.clear()
            if self._stop.is_set():
                break
            try:
                events = self.poll_files() if changed else []
                if self._background_changed:
                    events.extend(self.poll_background_items())
                    self._background_changed = False
                if time.monotonic() - last_tcc >= 10:
                    events.extend(self.poll_tcc())
                    last_tcc = time.monotonic()
                if self._extensions_changed.is_set() or time.monotonic() - last_extensions >= 60:
                    self._extensions_changed.clear()
                    base = Path.home() / "Library/Application Support"
                    roots = [
                        base / name
                        for name in (
                            "Google/Chrome",
                            "Microsoft Edge",
                            "BraveSoftware/Brave-Browser",
                            "Firefox/Profiles",
                        )
                    ]
                    for event in scan_extension_manifests(roots):
                        signature = event.model_dump_json(exclude={"id", "ts"})
                        if self._extension_state.get(event.requester.key) != signature:
                            events.append(event)
                            self._extension_state[event.requester.key] = signature
                    last_extensions = time.monotonic()
                self._latest = events or self._latest
                for event in events:
                    self._emit(event)
            except Exception:
                continue

    def start(self, emit: Emit) -> None:
        self._emit = emit
        self._tcc = self.read_tcc()
        self.diff_tcc({}, self._tcc)
        self.poll_files()
        from privacy_guardian.sensors.filesystem import PathMonitor

        self._path_monitor = PathMonitor(self.watch_paths, self._fs_changed.set)
        self._path_monitor.start()
        base = Path.home() / "Library/Application Support"
        browser_roots = [
            base / name
            for name in (
                "Google/Chrome",
                "Microsoft Edge",
                "BraveSoftware/Brave-Browser",
                "Firefox/Profiles",
            )
        ]

        def extensions_changed() -> None:
            self._extensions_changed.set()
            self._fs_changed.set()

        self._extension_monitor = PathMonitor(
            browser_roots,
            extensions_changed,
            path_filter=lambda path: path.name in {"manifest.json", "extensions.json"},
        )
        self._extension_monitor.start()

        self._thread = threading.Thread(target=self._loop, daemon=True, name="guardian-macos")
        self._thread.start()
        if sys.platform == "darwin" and not self._injected:
            self._log_thread = threading.Thread(
                target=self._logs, daemon=True, name="guardian-tcc-log"
            )
            self._log_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._fs_changed.set()
        if self._path_monitor:
            self._path_monitor.stop()
        if self._extension_monitor:
            self._extension_monitor.stop()
        if self._log_process:
            self._log_process.terminate()
        if self._thread:
            self._thread.join(timeout=2)

    def permissions_status(self) -> dict[str, bool]:
        fda = False
        for path in self.tcc_paths:
            try:
                with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.1) as connection:
                    connection.execute("SELECT 1 FROM access LIMIT 1").fetchone()
                    fda = True
            except (OSError, sqlite3.Error):
                continue
        try:
            accessibility = bool(self.backend.accessibility())
        except (ImportError, AttributeError):
            accessibility = False
        return {"full_disk_access": fda, "accessibility": accessibility}

    def foreground_requester(self) -> Requester:
        return enrich_requester(self.backend.foreground())

    def snapshot(self, requester: Requester | None = None) -> list[PrivacyEvent]:
        requester = requester or self.foreground_requester()
        events = self.diff_tcc({}, self.read_tcc())
        return [event for event in events if event.requester.key == requester.key] + [
            event for event in self._latest if event.requester.key == requester.key
        ]

    def open_settings(self, permission: str) -> None:
        pane = {
            "full_disk": "AllFiles",
            "accessibility": "Accessibility",
            "camera": "Camera",
            "microphone": "Microphone",
            "screen": "ScreenCapture",
            "location": "LocationServices",
            "contacts": "Contacts",
            "calendar": "Calendars",
            "automation": "Automation",
            "input_monitoring": "ListenEvent",
            "files": "FilesAndFolders",
            "photos": "Photos",
            "bluetooth": "Bluetooth",
        }.get(permission, "AllFiles")
        # System Settings (macOS 13+) moved the privacy anchors out of the old pane id.
        import platform

        try:
            major = int(platform.mac_ver()[0].split(".")[0] or 0)
        except ValueError:
            major = 0
        prefix = (
            "com.apple.settings.PrivacySecurity.extension"
            if major >= 13
            else "com.apple.preference.security"
        )
        self.backend.open_url(f"x-apple.systempreferences:{prefix}?Privacy_{pane}")

    def set_autostart(self, enabled: bool) -> None:
        if sys.platform != "darwin":
            return
        target = Path.home() / "Library/LaunchAgents/com.privacyguardian.app.plist"
        import os

        domain = f"gui/{os.getuid()}"
        if not enabled:
            subprocess.run(
                ["/bin/launchctl", "bootout", domain + "/com.privacyguardian.app"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            target.unlink(missing_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        command = (
            [sys.executable]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "privacy_guardian"]
        )
        target.write_bytes(
            plistlib.dumps(
                {
                    "Label": "com.privacyguardian.app",
                    "ProgramArguments": command,
                    "RunAtLoad": True,
                    "KeepAlive": {"SuccessfulExit": False},
                    "ProcessType": "Interactive",
                }
            )
        )
        subprocess.run(
            ["/bin/launchctl", "bootstrap", domain, str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
