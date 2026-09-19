from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import psutil
import pytest
import pytest_asyncio
from aiohttp import web
from playwright.async_api import BrowserContext, Worker, async_playwright

from privacy_guardian.config import Settings
from privacy_guardian.core.ipc.transport import send_request
from privacy_guardian.util import installation
from tests.e2e.fixture_server import FixtureState, create_fixture_app

ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_TOLERANCE = 1.25


@dataclass
class RealBrowser:
    context: BrowserContext
    data_dir: Path
    extension_id: str
    worker: Worker
    profile_dir: Path
    service_pid: int
    bridge_ready_seconds: float


async def stop_subprocess(process: asyncio.subprocess.Process, timeout: float = 5) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout)
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await asyncio.wait_for(process.wait(), timeout)


def kill_profile_processes(profile_dir: Path) -> None:
    matching: list[psutil.Process] = []
    for process in psutil.Process().children(recursive=True):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            if str(profile_dir) in " ".join(process.cmdline()):
                matching.append(process)
    matching_pids = {process.pid for process in matching}
    roots: list[psutil.Process] = []
    for process in matching:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            if process.ppid() not in matching_pids:
                roots.append(process)
    owned_by_pid: dict[int, psutil.Process] = {process.pid: process for process in roots}
    for root in roots:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            for descendant in root.children(recursive=True):
                owned_by_pid[descendant.pid] = descendant
    owned = list(owned_by_pid.values())
    for process in reversed(owned):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.kill()
    psutil.wait_procs(owned, timeout=3)


@pytest_asyncio.fixture
async def fixture_site(unused_tcp_port: int) -> AsyncIterator[tuple[str, FixtureState]]:
    state = FixtureState()
    runner = web.AppRunner(create_fixture_app(state))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    try:
        yield f"http://127.0.0.1:{unused_tcp_port}", state
    finally:
        await runner.cleanup()


@pytest.fixture
def installed_native_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Settings]:
    short_root = tempfile.TemporaryDirectory(
        prefix="pg-e2e-", dir="/tmp" if sys.platform != "win32" else None
    )
    data_dir = Path(short_root.name) / "data"
    browser_root = tmp_path / "browser-config"
    chrome_profile_hosts = tmp_path / "chromium-profile/NativeMessagingHosts"
    locations = {
        "chrome": chrome_profile_hosts,
        "edge": browser_root / "Microsoft Edge/NativeMessagingHosts",
        "brave": browser_root / "BraveSoftware/Brave-Browser/NativeMessagingHosts",
        "firefox": browser_root / "Mozilla/NativeMessagingHosts",
    }
    monkeypatch.setattr(installation, "manifest_locations", lambda: locations)
    settings = Settings(
        data_dir=data_dir,
        autostart=False,
        onboarding_complete=True,
        analysis_timeout_seconds=20,
    )
    registry_backup: dict[str, list[tuple[str, object, int]] | None] = {}
    if sys.platform == "win32":
        import winreg

        vendors = (
            r"Google\Chrome",
            r"Microsoft\Edge",
            r"BraveSoftware\Brave-Browser",
            "Mozilla",
        )
        for vendor in vendors:
            key_path = rf"Software\{vendor}\NativeMessagingHosts\{installation.HOST_NAME}"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    values: list[tuple[str, object, int]] = []
                    index = 0
                    while True:
                        try:
                            values.append(winreg.EnumValue(key, index))
                            index += 1
                        except OSError:
                            break
                    registry_backup[key_path] = values
            except FileNotFoundError:
                registry_backup[key_path] = None
    try:
        installation.install(settings)
        yield settings
    finally:
        if sys.platform == "win32":
            import winreg

            for key_path, previous_values in registry_backup.items():
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
                if previous_values is not None:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                        for name, value, value_type in previous_values:
                            winreg.SetValueEx(key, name, 0, value_type, value)
        database = settings.data_dir / "guardian.sqlite3"
        if database.exists():
            with sqlite3.connect(database) as connection:
                prefixes = {
                    str(row[0])[:8] + "-"
                    for row in connection.execute(
                        "SELECT id FROM events WHERE event_type='file_upload'"
                    )
                }
            artifact_folder = Path.home() / "Downloads/PrivacyGuardian"
            if artifact_folder.is_dir():
                for artifact in artifact_folder.iterdir():
                    if artifact.is_file() and any(
                        artifact.name.startswith(prefix) for prefix in prefixes
                    ):
                        artifact.unlink()
        short_root.cleanup()


@pytest_asyncio.fixture
async def real_browser(
    installed_native_host: Settings, tmp_path: Path
) -> AsyncIterator[RealBrowser]:
    settings = installed_native_host
    profile_dir = tmp_path / "chromium-profile"
    environment = os.environ.copy()
    environment["PRIVACY_GUARDIAN_DATA_DIR"] = str(settings.data_dir)
    service = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "privacy_guardian",
        "--headless",
        cwd=ROOT,
        env=environment,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    playwright = None
    context = None
    try:
        for _attempt in range(200):
            if service.returncode is not None:
                raise RuntimeError("service exited before readiness")
            try:
                response = await send_request(
                    settings.data_dir,
                    {"v": 1, "id": "e2e-ready", "type": "ping", "payload": {}},
                    timeout=0.1,
                )
                if response.get("ok"):
                    break
            except (OSError, TimeoutError, ConnectionError):
                pass
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("service did not bind its control socket")

        bridge_started = time.perf_counter()
        playwright = await async_playwright().start()
        extension = ROOT / "extension"
        context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chromium",
            headless=os.getenv("PRIVACY_GUARDIAN_E2E_HEADED") != "1",
            args=[
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                "--host-resolver-rules=MAP tracker-one.test 127.0.0.1,MAP ads-two.test 127.0.0.1,MAP metrics-three.test 127.0.0.1",
            ],
            env=environment,
        )
        worker = (
            context.service_workers[0]
            if context.service_workers
            else await context.wait_for_event("serviceworker", timeout=10_000)
        )
        extension_id = worker.url.split("/")[2]
        assert extension_id == installation.CHROME_ID
        native_ready = await worker.evaluate(
            "() => native('ping',{browser:'chromium-e2e-ready'},5000)"
        )
        assert native_ready.get("status") == "ready", native_ready
        assert native_ready.get("protocol") == 1, native_ready
        bridge_ready_seconds = time.perf_counter() - bridge_started
        print(f"cold Chromium native-bridge readiness: {bridge_ready_seconds:.6f}s")
        assert bridge_ready_seconds <= 5 * PERFORMANCE_TOLERANCE
        yield RealBrowser(
            context=context,
            data_dir=settings.data_dir,
            extension_id=extension_id,
            worker=worker,
            profile_dir=profile_dir,
            service_pid=service.pid,
            bridge_ready_seconds=bridge_ready_seconds,
        )
    finally:
        if context is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(context.close(), 5)
        kill_profile_processes(profile_dir)
        if playwright is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(playwright.stop(), 5)
        await stop_subprocess(service)
