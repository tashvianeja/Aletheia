from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

import psutil
import pytest
from aiohttp import web

from privacy_guardian.config import Settings
from privacy_guardian.core.ipc.transport import send_request
from privacy_guardian.util import installation

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]
WEB_EXT = ROOT / "build/firefox-tools/node_modules/web-ext/bin/web-ext.js"


def firefox_binary() -> str | None:
    candidates = (
        Path("/Applications/Firefox.app/Contents/MacOS/firefox"),
        Path("/opt/homebrew/bin/firefox"),
        Path("C:/Program Files/Mozilla Firefox/firefox.exe"),
    )
    return next((str(path) for path in candidates if path.exists()), shutil.which("firefox"))


def host_manifest(data_dir: Path) -> dict[str, Any]:
    if sys.platform == "win32":
        executable = Path(sys.executable).parent / "privacy-guardian-host.exe"
    else:
        executable = data_dir / "privacy-guardian-host"
        executable.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" -m privacy_guardian.core.ipc.native_host "$@"\n',
            encoding="utf-8",
        )
        executable.chmod(0o700)
    return {
        "name": installation.HOST_NAME,
        "description": "Privacy Guardian Firefox smoke host",
        "path": str(executable),
        "type": "stdio",
        "allowed_extensions": [installation.FIREFOX_ID],
    }


@contextlib.contextmanager
def registered_firefox_host(data_dir: Path):
    manifest = host_manifest(data_dir)
    if sys.platform == "win32":
        import winreg

        key_path = rf"Software\Mozilla\NativeMessagingHosts\{installation.HOST_NAME}"
        previous_values: list[tuple[str, object, int]] | None = None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                previous_values = []
                index = 0
                while True:
                    try:
                        previous_values.append(winreg.EnumValue(key, index))
                        index += 1
                    except OSError:
                        break
        except FileNotFoundError:
            pass
        target = data_dir / "firefox" / f"{installation.HOST_NAME}.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(manifest), encoding="utf-8")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(target))
        try:
            yield
        finally:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            if previous_values is not None:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    for name, value, value_type in previous_values:
                        winreg.SetValueEx(key, name, 0, value_type, value)
        return

    target = installation.manifest_locations().get("firefox")
    if target is None:
        target = Path.home() / ".mozilla/native-messaging-hosts"
    path = target / f"{installation.HOST_NAME}.json"
    previous = path.read_bytes() if path.exists() else None
    previous_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    target.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        yield
    finally:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)
            if previous_mode is not None:
                path.chmod(previous_mode)


async def stop_process_tree(process: asyncio.subprocess.Process) -> None:
    try:
        members = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        members = []
    for member in reversed(members):
        with contextlib.suppress(psutil.NoSuchProcess):
            member.terminate()
    if process.returncode is None:
        process.terminate()
    _, alive = psutil.wait_procs(members, timeout=3)
    for member in alive:
        with contextlib.suppress(psutil.NoSuchProcess):
            member.kill()
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), 3)
    if process.returncode is None:
        process.kill()
        await process.wait()


@pytest.mark.asyncio
async def test_firefox_fixed_id_performs_real_native_host_ping(
    tmp_path: Path, unused_tcp_port: int
) -> None:
    binary = firefox_binary()
    node = shutil.which("node")
    if binary is None or node is None or not WEB_EXT.exists():
        pytest.fail("Firefox, Node.js, and web-ext are required for the native-host smoke test")
    data_dir = tmp_path / "data"
    Settings(data_dir=data_dir, autostart=False, onboarding_complete=True).save()
    environment = os.environ.copy()
    environment["PRIVACY_GUARDIAN_DATA_DIR"] = str(data_dir)
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
        try:
            ready = await send_request(
                data_dir, {"v": 1, "id": "firefox-ready", "type": "ping", "payload": {}}
            )
            if ready.get("ok"):
                break
        except (OSError, TimeoutError, ConnectionError):
            await asyncio.sleep(0.025)
    else:
        pytest.fail("service did not become ready for Firefox")

    response_future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

    async def result(request: web.Request) -> web.Response:
        if not response_future.done():
            response_future.set_result(await request.json())
        return web.Response(status=204)

    callback = web.Application()
    callback.router.add_post("/native-result", result)
    runner = web.AppRunner(callback)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    extension = tmp_path / "firefox-extension"
    shutil.copytree(ROOT / "extension", extension)
    shutil.copyfile(extension / "manifest.firefox.json", extension / "manifest.json")
    with (extension / "background.js").open("a", encoding="utf-8") as script:
        script.write(
            "\nnative('ping',{browser:'firefox-smoke'},5000)"
            f".then(value=>fetch('http://127.0.0.1:{unused_tcp_port}/native-result',"
            "{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}))"
            f".catch(error=>fetch('http://127.0.0.1:{unused_tcp_port}/native-result',"
            "{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({error:String(error)})}));\n"
        )
    browser: asyncio.subprocess.Process | None = None
    try:
        with registered_firefox_host(data_dir):
            browser = await asyncio.create_subprocess_exec(
                node,
                str(WEB_EXT),
                "run",
                "--source-dir",
                str(extension),
                "--firefox",
                binary,
                "--firefox-profile",
                str(tmp_path / "firefox-profile"),
                "--profile-create-if-missing",
                "--keep-profile-changes",
                "--no-reload",
                "--no-input",
                "--args=-headless",
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                response = await asyncio.wait_for(response_future, 20)
            except TimeoutError:
                await stop_process_tree(browser)
                output = await asyncio.wait_for(browser.stdout.read(), 1) if browser.stdout else b""
                pytest.fail(f"Firefox native ping timed out: {output.decode(errors='replace')}")
            assert response == {
                "version": "0.1.0",
                "protocol": 1,
                "status": "ready",
                "commands": [],
            }
    finally:
        if browser is not None and browser.returncode is None:
            await stop_process_tree(browser)
        await runner.cleanup()
        service.terminate()
        await service.wait()
