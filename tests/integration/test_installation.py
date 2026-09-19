from __future__ import annotations

import asyncio
import json
import os
import struct
import subprocess
import sys
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

from privacy_guardian.config import Settings
from privacy_guardian.core.ipc.protocol import decode_message, encode_message
from privacy_guardian.core.ipc.transport import ControlServer
from privacy_guardian.util import installation


def isolated_locations(root: Path) -> dict[str, Path]:
    return {name: root / name for name in ("chrome", "edge", "brave", "firefox")}


class FakeRegistryKey(AbstractContextManager["FakeRegistryKey"]):
    def __init__(self, path: str) -> None:
        self.path = path

    def __exit__(self, *args: object) -> None:
        return None


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    def CreateKey(self, _root: object, path: str) -> FakeRegistryKey:
        return FakeRegistryKey(path)

    def SetValueEx(
        self, key: FakeRegistryKey, _name: str, _reserved: int, _kind: int, value: str
    ) -> None:
        self.values[key.path] = value

    def DeleteKey(self, _root: object, path: str) -> None:
        if path not in self.values:
            raise FileNotFoundError(path)
        self.deleted.append(path)
        del self.values[path]


def isolate_windows_registry(monkeypatch: pytest.MonkeyPatch) -> FakeWinreg | None:
    if sys.platform != "win32":
        return None
    registry = FakeWinreg()
    real_import = installation.importlib.import_module
    monkeypatch.setattr(
        installation.importlib,
        "import_module",
        lambda name: registry if name == "winreg" else real_import(name),
    )
    return registry


def test_install_writes_least_privilege_browser_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations = isolated_locations(tmp_path / "browser-config")
    monkeypatch.setattr(installation, "manifest_locations", lambda: locations)
    registry = isolate_windows_registry(monkeypatch)
    settings = Settings(data_dir=tmp_path / "data", autostart=False)

    installed = installation.install(settings)

    host = settings.data_dir / "privacy-guardian-host"
    if sys.platform == "win32":
        assert host not in installed
        assert registry is not None and len(registry.values) == 4
        expected_locations = isolated_locations(settings.data_dir)
    else:
        assert host in installed
        assert host.stat().st_mode & 0o777 == 0o700
        expected_locations = locations
    for browser, folder in expected_locations.items():
        manifest_path = folder / f"{installation.HOST_NAME}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sys.platform == "win32":
            assert manifest["path"].endswith("privacy-guardian-host.exe")
        else:
            assert manifest["path"] == str(host)
        assert manifest["type"] == "stdio"
        if os.name != "nt":
            assert manifest_path.stat().st_mode & 0o777 == 0o600
        if browser == "firefox":
            assert manifest["allowed_extensions"] == [installation.FIREFOX_ID]
            assert "allowed_origins" not in manifest
        else:
            assert manifest["allowed_origins"] == [f"chrome-extension://{installation.CHROME_ID}/"]
            assert "allowed_extensions" not in manifest


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name == "nt", reason="POSIX host wrapper; packaged Windows host has its own smoke test"
)
async def test_installed_native_host_performs_real_stdio_to_authenticated_service_handshake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations = isolated_locations(tmp_path / "browser-config")
    monkeypatch.setattr(installation, "manifest_locations", lambda: locations)
    short_root = tempfile.TemporaryDirectory(
        prefix="pg-host-", dir="/tmp" if sys.platform != "win32" else None
    )
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
    from privacy_guardian.llm import client as llm_client

    monkeypatch.setattr(llm_client, "delete_api_key", lambda: None)
    locations = isolated_locations(tmp_path / "browser-config")
    monkeypatch.setattr(installation, "manifest_locations", lambda: locations)
    registry = isolate_windows_registry(monkeypatch)
    if sys.platform == "win32":
        from privacy_guardian.sensors.platform import windows

        monkeypatch.setattr(windows.WindowsRegistry, "set_autostart", lambda *_args: None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    settings = Settings(data_dir=tmp_path / "data", autostart=False)
    installation.install(settings)
    actual_locations = (
        isolated_locations(settings.data_dir) if sys.platform == "win32" else locations
    )
    unrelated_data = settings.data_dir / "keep-me.txt"
    unrelated_data.write_text("unrelated user data", encoding="utf-8")
    unrelated_browser = actual_locations["chrome"] / "other.vendor.host.json"
    unrelated_browser.write_text("{}", encoding="utf-8")

    installation.uninstall(settings)

    assert unrelated_data.read_text(encoding="utf-8") == "unrelated user data"
    assert unrelated_browser.exists()
    assert all(
        not (folder / f"{installation.HOST_NAME}.json").exists()
        for folder in actual_locations.values()
    )
    if registry is not None:
        assert not registry.values
        assert len(registry.deleted) == 4
