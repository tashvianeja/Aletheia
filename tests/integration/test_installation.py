from __future__ import annotations

import asyncio
import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path

import pytest

from privacy_guardian.config import Settings
from privacy_guardian.core.ipc.protocol import decode_message, encode_message
from privacy_guardian.core.ipc.transport import ControlServer
from privacy_guardian.util import installation


def isolated_locations(root: Path) -> dict[str, Path]:
    return {name: root / name for name in ("chrome", "edge", "brave", "firefox")}


def test_install_writes_least_privilege_browser_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations = isolated_locations(tmp_path / "browser-config")
    monkeypatch.setattr(installation, "manifest_locations", lambda: locations)
    settings = Settings(data_dir=tmp_path / "data", autostart=False)

    installed = installation.install(settings)

    host = settings.data_dir / "privacy-guardian-host"
    assert host in installed
    assert host.stat().st_mode & 0o777 == 0o700
    for browser, folder in locations.items():
        manifest_path = folder / f"{installation.HOST_NAME}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["path"] == str(host)
        assert manifest["type"] == "stdio"
        assert manifest_path.stat().st_mode & 0o777 == 0o600
        if browser == "firefox":
            assert manifest["allowed_extensions"] == [installation.FIREFOX_ID]
            assert "allowed_origins" not in manifest
        else:
            assert manifest["allowed_origins"] == [f"chrome-extension://{installation.CHROME_ID}/"]
            assert "allowed_extensions" not in manifest


@pytest.mark.asyncio
async def test_installed_native_host_performs_real_stdio_to_authenticated_service_handshake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations = isolated_locations(tmp_path / "browser-config")
    monkeypatch.setattr(installation, "manifest_locations", lambda: locations)
    short_root = tempfile.TemporaryDirectory(prefix="pg-host-", dir="/tmp")
    settings = Settings(data_dir=Path(short_root.name), autostart=False)
    installation.install(settings)

    async def handler(message: dict[str, object]) -> dict[str, object]:
        return {
            "v": 1,
            "id": str(message["id"]),
            "ok": True,
            "result": {"transport": "native-stdio-control-socket"},
            "error": None,
        }

    server = ControlServer(settings.data_dir, handler)  # type: ignore[arg-type]
    await server.start()
    environment = os.environ.copy()
    environment["PRIVACY_GUARDIAN_DATA_DIR"] = str(settings.data_dir)
    process = await asyncio.create_subprocess_exec(
        str(settings.data_dir / "privacy-guardian-host"),
        f"chrome-extension://{installation.CHROME_ID}/",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write(
            encode_message({"v": 1, "id": "real-host", "type": "ping", "payload": {}})
        )
        await process.stdin.drain()
        header = await asyncio.wait_for(process.stdout.readexactly(4), 5)
        length = struct.unpack("<I", header)[0]
        response = decode_message(await asyncio.wait_for(process.stdout.readexactly(length), 5))
        assert response["ok"] is True
        assert response["result"] == {"transport": "native-stdio-control-socket"}
    finally:
        process.stdin.close()
        await process.wait()
        await server.stop()
        short_root.cleanup()
    assert process.returncode == 0


def test_uninstall_removes_only_known_product_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations = isolated_locations(tmp_path / "browser-config")
    monkeypatch.setattr(installation, "manifest_locations", lambda: locations)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    settings = Settings(data_dir=tmp_path / "data", autostart=False)
    installation.install(settings)
    unrelated_data = settings.data_dir / "keep-me.txt"
    unrelated_data.write_text("unrelated user data", encoding="utf-8")
    unrelated_browser = locations["chrome"] / "other.vendor.host.json"
    unrelated_browser.write_text("{}", encoding="utf-8")

    installation.uninstall(settings)

    assert unrelated_data.read_text(encoding="utf-8") == "unrelated user data"
    assert unrelated_browser.exists()
    assert all(
        not (folder / f"{installation.HOST_NAME}.json").exists() for folder in locations.values()
    )
