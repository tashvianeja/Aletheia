from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from playwright.async_api import BrowserContext, Worker, async_playwright

from privacy_guardian.config import Settings
from privacy_guardian.core.ipc.transport import send_request
from privacy_guardian.util import installation
from tests.e2e.fixture_server import FixtureState, create_fixture_app

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RealBrowser:
    context: BrowserContext
    data_dir: Path
    extension_id: str
    worker: Worker


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
    registry_backup: dict[str, str | None] = {}
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
                    registry_backup[key_path] = str(winreg.QueryValueEx(key, "")[0])
            except FileNotFoundError:
                registry_backup[key_path] = None
    try:
        installation.install(settings)
        yield settings
    finally:
        if sys.platform == "win32":
            import winreg

            for key_path, previous in registry_backup.items():
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
                if previous is not None:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, previous)
        short_root.cleanup()


@pytest_asyncio.fixture
async def real_browser(
    installed_native_host: Settings, tmp_path: Path
) -> AsyncIterator[RealBrowser]:
    settings = installed_native_host
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
        stderr=asyncio.subprocess.PIPE,
    )
    for _attempt in range(200):
        if service.returncode is not None:
            stderr = await service.stderr.read() if service.stderr else b""
            raise RuntimeError(f"service exited before readiness: {stderr.decode()}")
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
        service.terminate()
        await service.wait()
        raise RuntimeError("service did not bind its control socket")

    playwright = await async_playwright().start()
    extension = ROOT / "extension"
    context = await playwright.chromium.launch_persistent_context(
        str(tmp_path / "chromium-profile"),
        channel="chromium",
        headless=os.getenv("PRIVACY_GUARDIAN_E2E_HEADED") != "1",
        args=[
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
        ],
        env=environment,
    )
    worker = (
        context.service_workers[0]
        if context.service_workers
        else await context.wait_for_event("serviceworker", timeout=10_000)
    )
    extension_id = worker.url.split("/")[2]
    try:
        assert extension_id == installation.CHROME_ID
        yield RealBrowser(
            context=context,
            data_dir=settings.data_dir,
            extension_id=extension_id,
            worker=worker,
        )
    finally:
        await context.close()
        await playwright.stop()
        service.terminate()
        await service.wait()
