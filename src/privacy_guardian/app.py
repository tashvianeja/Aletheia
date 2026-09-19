from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import multiprocessing
import signal
import sys
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from privacy_guardian.config import Settings


def _windows_browser_installed(executable: str) -> bool:
    import shutil

    if shutil.which(executable):
        return True
    # Windows browsers are not on PATH; they register an absolute path under App Paths,
    # which for some installers only exists in the 32-bit registry view.
    import winreg

    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                    location = str(winreg.QueryValueEx(key, "")[0]).strip('"')
            except OSError:
                continue
            if location and Path(location).exists():
                return True
    return False


def diagnose(settings: Settings) -> dict[str, Any]:
    import importlib.metadata
    import shutil
    import sqlite3

    from privacy_guardian.util.installation import HOST_NAME, manifest_locations

    counts: dict[str, int] = {}
    database = settings.data_dir / "guardian.sqlite3"
    if database.exists():
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                for table in (
                    "events",
                    "decisions",
                    "user_responses",
                    "preferences",
                    "learned_rules",
                ):
                    counts[table] = int(
                        connection.execute(
                            {
                                "events": "SELECT COUNT(*) FROM events",
                                "decisions": "SELECT COUNT(*) FROM decisions",
                                "user_responses": "SELECT COUNT(*) FROM user_responses",
                                "preferences": "SELECT COUNT(*) FROM preferences",
                                "learned_rules": "SELECT COUNT(*) FROM learned_rules",
                            }[table]
                        ).fetchone()[0]
                    )
        except sqlite3.Error:
            counts = {}
    try:
        from privacy_guardian.sensors.platform import create_adapter

        permissions = create_adapter().permissions_status()
    except (RuntimeError, OSError):
        permissions = {}
    locations = manifest_locations()
    registrations = {
        browser: (folder / f"{HOST_NAME}.json").exists() for browser, folder in locations.items()
    }
    if sys.platform == "win32":
        registrations = {
            browser: (settings.data_dir / browser / f"{HOST_NAME}.json").exists()
            for browser in ("chrome", "edge", "brave", "firefox")
        }
    browsers = (
        {
            name: Path("/Applications", app).exists()
            for name, app in {
                "chrome": "Google Chrome.app",
                "edge": "Microsoft Edge.app",
                "brave": "Brave Browser.app",
                "firefox": "Firefox.app",
            }.items()
        }
        if sys.platform == "darwin"
        else {
            name: _windows_browser_installed(exe)
            for name, exe in {
                "chrome": "chrome.exe",
                "edge": "msedge.exe",
                "brave": "brave.exe",
                "firefox": "firefox.exe",
            }.items()
        }
    )
    return {
        "version": importlib.metadata.version("privacy-guardian"),
        "platform": sys.platform,
        "python": ".".join(str(i) for i in sys.version_info[:3]),
        "ocr_available": bool(shutil.which("tesseract")),
        "llm_enabled": settings.llm.enabled,
        "database_present": database.exists(),
        "database_counts": counts,
        "token_present": (settings.data_dir / "ipc.token").exists(),
        "native_host_registrations": registrations,
        "browsers_detected": browsers,
        "permissions": permissions,
    }


def main() -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="privacy-guardian")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--native-host", action="store_true")
    parser.add_argument("--install-native-host", action="store_true")
    parser.add_argument("--no-autostart", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    arguments, _ = parser.parse_known_args()
    if arguments.native_host:
        from privacy_guardian.core.ipc.native_host import main as host_main

        return host_main()
    settings = Settings.load()
    if arguments.no_autostart:
        settings.autostart = False
    if arguments.diagnose:
        print(json.dumps(diagnose(settings), indent=2))
        return 0
    if arguments.install_native_host or arguments.uninstall:
        from privacy_guardian.util.installation import install, uninstall

        if arguments.uninstall:
            uninstall(settings)
        else:
            install(settings)
        return 0
    from privacy_guardian.core.ipc.transport import send_request
    from privacy_guardian.util.instance import InstanceLock
    from privacy_guardian.util.logging import configure_logging

    lock = InstanceLock(settings.data_dir / "guardian.lock")
    if not lock.acquire():
        with contextlib.suppress(OSError):
            asyncio.run(
                send_request(
                    settings.data_dir, {"v": 1, "id": "focus", "type": "focus", "payload": {}}
                )
            )
        return 0
    configure_logging(settings.data_dir, settings.log_level)
    if arguments.headless:
        from privacy_guardian.core.service import Service

        async def run() -> None:
            service = Service(settings)
            await service.start()
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            if sys.platform != "win32":
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, stop.set)
            try:
                await stop.wait()
            finally:
                await service.stop()

        try:
            asyncio.run(run())
        finally:
            lock.release()
        return 0
    from PySide6.QtCore import QObject, QTimer, QUrl, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

    from privacy_guardian.core.events import Decision, UserResponse
    from privacy_guardian.core.service import Service
    from privacy_guardian.ui.dashboard import Dashboard
    from privacy_guardian.ui.deepcheck import DeepCheckWindow
    from privacy_guardian.ui.onboarding import Onboarding
    from privacy_guardian.ui.popup import PopupQueue
    from privacy_guardian.ui.tray import GuardianTray
    from privacy_guardian.util.i18n import tr

    class Bridge(QObject):
        decision_ready = Signal(object)
        report_ready = Signal(object)
        focus_requested = Signal()
        deep_check_requested = Signal()
        error = Signal(str)
        update_ready = Signal(str)
        action_ready = Signal(str, str)

    class Controller:
        def __init__(self) -> None:
            self.settings = settings
            self.dialog_parent = QWidget()
            self.core = Service(settings)
            self.loop = asyncio.new_event_loop()
            self.bridge = Bridge()
            self.thread = threading.Thread(
                target=self._run_loop, daemon=True, name="guardian-service"
            )
            self.dashboard: Dashboard | None = None
            self.deepcheck_window: DeepCheckWindow | None = None
            self.onboarding: Onboarding | None = None
            self.clipboard: Any = None
            self._closing = False
            self.core.decision_listeners.append(self.bridge.decision_ready.emit)
            self.core.focus_listeners.append(self.bridge.focus_requested.emit)
            self.core.action_listeners.append(self.bridge.action_ready.emit)
            self.bridge.action_ready.connect(self.actuate)
            self.bridge.decision_ready.connect(self.show_decision)
            self.bridge.report_ready.connect(self.show_report)
            self.bridge.update_ready.connect(
                lambda message: QMessageBox.information(self.dialog_parent, tr("updates"), message)
            )
            self.bridge.focus_requested.connect(self.show_dashboard)
            self.bridge.deep_check_requested.connect(self.deep_check)
            from privacy_guardian.sensors.hotkey import GlobalHotkey

            self.hotkey = GlobalHotkey(settings.hotkey, self.bridge.deep_check_requested.emit)
            if not arguments.smoke_test:
                self.hotkey.start()
            self.bridge.error.connect(
                lambda message: QMessageBox.warning(self.dialog_parent, tr("app_name"), message)
            )
            self.tray = GuardianTray(self)
            self.popups = PopupQueue(self)
            self.popups.anchor = self.tray.geometry()
            self.thread.start()
            self.submit(self._start())
            self.supervisor = QTimer(self.bridge)
            self.supervisor.timeout.connect(self.supervise)
            self.supervisor.start(2000)

        def _run_loop(self) -> None:
            asyncio.set_event_loop(self.loop)
            self.loop.set_exception_handler(
                lambda _loop, context: logging.getLogger(__name__).error(
                    "service task failed",
                    extra={"error_type": type(context.get("exception")).__name__},
                )
            )
            self.loop.run_forever()

        async def _start(self) -> None:
            await self.core.start()
            if not arguments.smoke_test:
                from privacy_guardian.sensors.clipboard import ClipboardMonitor
                from privacy_guardian.sensors.platform import create_adapter

                self.core.adapter = create_adapter()

                def emit(event: Any) -> None:
                    self.submit(self.core.bus.publish(event))

                await asyncio.to_thread(self.core.adapter.start, emit)
                self.clipboard = ClipboardMonitor(
                    self.core.adapter.backend,
                    self.core.pool,
                    emit,
                    self.core.preferences.clipboard_allowlist,
                )
                self.clipboard.start()

        def submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
            future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)

            def completed(value: Future[Any]) -> None:
                if not value.cancelled() and value.exception():
                    logging.getLogger(__name__).error(
                        "service operation failed",
                        extra={"error_type": type(value.exception()).__name__},
                    )

            future.add_done_callback(completed)
            return future

        def show_decision(self, decision: Decision) -> None:
            self.tray.set_state("attention")
            self.popups.enqueue(decision)

        def submit_response(self, event_id: str, action: str, remember: bool) -> Future[Any]:
            future = self.submit(
                self.core.respond(UserResponse(event_id=event_id, action=action, remember=remember))
            )

            def action_finished(value: Future[Any]) -> None:
                if not value.cancelled() and value.exception():
                    self.bridge.error.emit(tr("action_failed"))
                    if event_id in self.core.decisions and event_id not in self.core.actions:
                        self.bridge.decision_ready.emit(self.core.decisions[event_id])

            future.add_done_callback(action_finished)
            return future

        def actuate(self, event_id: str, action: str) -> None:
            if action == "open_settings":
                self.open_settings(
                    getattr(self.core.events.get(event_id), "permission", "full_disk")
                )
            elif action == "clear_clipboard" and self.core.adapter:
                self.core.adapter.backend.clear_clipboard()
            elif action in {"learn_more", "view_details"}:
                self.show_dashboard()
            self.tray.set_state("idle")

        def supervise(self) -> None:
            if self._closing:
                return
            if self.thread.is_alive():
                return
            old = self.core
            if old.adapter:
                old.adapter.stop()
            old.pool.close()
            old.metadata_executor.shutdown(wait=False, cancel_futures=True)
            old._close_cloud()
            if old.control.server:
                old.control.server.close()
            if old.control.listener:
                old.control.listener.close()
            with contextlib.suppress(Exception):
                old.store.close()
            self.loop = asyncio.new_event_loop()
            self.core = Service(settings)
            self.core.decision_listeners.append(self.bridge.decision_ready.emit)
            self.core.focus_listeners.append(self.bridge.focus_requested.emit)
            self.core.action_listeners.append(self.bridge.action_ready.emit)
            self.thread = threading.Thread(
                target=self._run_loop, daemon=True, name="guardian-service"
            )
            self.thread.start()
            self.submit(self._start())
            self.tray.set_state("attention")
            self.tray.showMessage(tr("app_name"), tr("service_restarted"))

        def deep_check(self) -> None:
            foreground = self.core.adapter.foreground_requester() if self.core.adapter else None
            self.deepcheck_window = DeepCheckWindow(self)
            self.deepcheck_window.show()

            async def run_check() -> None:
                from privacy_guardian.deepcheck import run_deep_check

                report = await run_deep_check(self.core, foreground_requester=foreground)
                self.bridge.report_ready.emit(report)

            self.submit(run_check())

        def show_report(self, report: dict[str, Any]) -> None:
            if self.deepcheck_window:
                self.deepcheck_window.show_report(report)

        def pause(self, seconds: int) -> None:
            if seconds == 86400:
                from datetime import datetime, timedelta

                tomorrow = (datetime.now() + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                seconds = int((tomorrow - datetime.now()).total_seconds())
            self.loop.call_soon_threadsafe(self.core.pause, seconds)
            self.tray.set_state("paused" if seconds else "idle")

        def show_dashboard(self, tab: str = "history") -> None:
            if self.dashboard is None:
                self.dashboard = Dashboard(self)
            self.dashboard.tabs.setCurrentIndex(1 if tab == "preferences" else 0)
            self.dashboard.refresh()
            self.dashboard.show()
            self.dashboard.raise_()
            self.dashboard.activateWindow()

        def permissions_status(self) -> dict[str, bool]:
            return (
                self.core.adapter.permissions_status()
                if self.core.adapter
                else {"initializing": False}
            )

        def show_permissions(self) -> None:
            QMessageBox.information(
                self.dialog_parent,
                tr("permissions"),
                "\n".join(
                    f"{name}: {tr('enabled') if enabled else tr('disabled')}"
                    for name, enabled in self.permissions_status().items()
                ),
            )

        def show_extensions(self) -> None:
            QMessageBox.information(
                self.dialog_parent,
                tr("extensions"),
                tr("connected", count=len(self.core.connected_browsers)),
            )

        def show_onboarding(self) -> None:
            self.onboarding = Onboarding(self)
            self.onboarding.show()

        def open_settings(self, permission: str) -> None:
            if self.core.adapter:
                self.core.adapter.open_settings(permission)

        def open_extension_folder(self) -> None:
            folder = (
                Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "extension"
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

        def update_trackers(self) -> None:
            async def update() -> None:
                from privacy_guardian.util.tracker_update import update_tracker_list

                try:
                    count = await asyncio.to_thread(
                        update_tracker_list, settings.data_dir / "trackers.json"
                    )
                    self.bridge.update_ready.emit(tr("trackers_updated", count=count))
                except Exception:
                    self.bridge.update_ready.emit(tr("tracker_update_failed"))

            self.submit(update())

        def check_updates(self) -> None:
            async def check() -> None:
                import httpx
                from packaging.version import InvalidVersion, Version

                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                        response = await client.get(
                            "https://api.github.com/repos/tashvianeja/Privacy-Guardian/releases/latest",
                            headers={"Accept": "application/vnd.github+json"},
                        )
                        if response.status_code == 404:
                            self.bridge.update_ready.emit(tr("no_release"))
                            return
                        response.raise_for_status()
                        latest = str(response.json()["tag_name"]).lstrip("v")
                        current = str(diagnose(settings)["version"])
                        self.bridge.update_ready.emit(
                            tr("update_available", version=latest)
                            if Version(latest) > Version(current)
                            else tr("up_to_date", version=current)
                        )
                except (httpx.HTTPError, ValueError, KeyError, InvalidVersion):
                    self.bridge.update_ready.emit(tr("update_failed"))

            self.submit(check())

        def diagnostics(self) -> dict[str, Any]:
            return {
                **diagnose(settings),
                "permissions": self.permissions_status(),
                "browser_count": len(self.core.connected_browsers),
                "database_counts": self.core.store.diagnostics(),
            }

        def quit(self) -> None:
            app.quit()

        def shutdown(self) -> None:
            if self._closing:
                return
            self._closing = True
            self.supervisor.stop()
            self.hotkey.stop()
            if self.dashboard is not None:
                self.dashboard.close()

            async def stop() -> None:
                if self.clipboard:
                    await self.clipboard.stop()
                await self.core.stop()

            try:
                self.submit(stop()).result(timeout=5)
            except Exception:
                self.core.pool.close()
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
            lock.release()

    app = QApplication(sys.argv)
    app.setApplicationName("PrivacyGuardian")
    app.setOrganizationName("PrivacyGuardian")
    app.setQuitOnLastWindowClosed(False)
    controller = Controller()
    QTimer.singleShot(
        0, lambda: (settings.data_dir / "tray-ready").write_text("ready", encoding="ascii")
    )
    app.aboutToQuit.connect(controller.shutdown)
    app.commitDataRequest.connect(lambda _manager: controller.shutdown())
    sys.excepthook = lambda error_type, _error, _traceback: logging.getLogger(__name__).error(
        "ui operation failed", extra={"error_type": error_type.__name__}
    )
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(500)
    signal.signal(signal.SIGTERM, lambda _sig, _frame: app.quit())
    if arguments.smoke_test:
        QTimer.singleShot(2000, app.quit)
    elif not settings.onboarding_complete:
        QTimer.singleShot(500, controller.show_onboarding)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
