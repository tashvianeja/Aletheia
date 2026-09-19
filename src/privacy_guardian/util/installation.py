from __future__ import annotations

import contextlib
import importlib
import json
import shlex
import shutil
import sys
from pathlib import Path

from privacy_guardian.config import Settings

HOST_NAME = "com.privacyguardian.host"
CHROME_ID = "bfdjphkbgihhbonhnmjbbfhckdddonob"
FIREFOX_ID = "privacy-guardian@privacyguardian.local"


def manifest_locations(platform: str | None = None, home: Path | None = None) -> dict[str, Path]:
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "darwin":
        base = home / "Library/Application Support"
        return {
            "chrome": base / "Google/Chrome/NativeMessagingHosts",
            "edge": base / "Microsoft Edge/NativeMessagingHosts",
            "brave": base / "BraveSoftware/Brave-Browser/NativeMessagingHosts",
            "firefox": base / "Mozilla/NativeMessagingHosts",
        }
    return {}


def install(settings: Settings) -> list[Path]:
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    installed: list[Path] = []
    if sys.platform == "win32":
        executable = (
            Path(sys.executable).with_name("PrivacyGuardianHost.exe")
            if getattr(sys, "frozen", False)
            else Path(sys.executable).parent / "privacy-guardian-host.exe"
        )
    else:
        executable = settings.data_dir / "privacy-guardian-host"
        command = (
            [sys.executable, "--native-host"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "privacy_guardian.core.ipc.native_host"]
        )
        executable.write_text(
            "#!/bin/sh\nexec " + " ".join(shlex.quote(item) for item in command) + ' "$@"\n',
            encoding="utf-8",
        )
        executable.chmod(0o700)
        installed.append(executable)
    for browser in ("chrome", "edge", "brave", "firefox"):
        manifest: dict[str, object] = {
            "name": HOST_NAME,
            "description": "Local Privacy Guardian analysis bridge",
            "path": str(executable),
            "type": "stdio",
        }
        if browser == "firefox":
            manifest["allowed_extensions"] = [FIREFOX_ID]
        else:
            manifest["allowed_origins"] = [f"chrome-extension://{CHROME_ID}/"]
        if sys.platform == "darwin":
            folder = manifest_locations()[browser]
        else:
            folder = settings.data_dir / browser
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{HOST_NAME}.json"
        target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        target.chmod(0o600)
        installed.append(target)
        if sys.platform == "win32":
            winreg = importlib.import_module("winreg")
            vendor = {
                "chrome": "Google\\Chrome",
                "edge": "Microsoft\\Edge",
                "brave": "BraveSoftware\\Brave-Browser",
                "firefox": "Mozilla",
            }[browser]
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, rf"Software\{vendor}\NativeMessagingHosts\{HOST_NAME}"
            ) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(target))
    (settings.data_dir / "install-manifest.json").write_text(
        json.dumps([str(path) for path in installed]), encoding="utf-8"
    )
    settings.allowed_extension_ids = [CHROME_ID, FIREFOX_ID]
    settings.save()
    if settings.autostart:
        from privacy_guardian.sensors.platform import create_adapter

        create_adapter().set_autostart(True)
    return installed


def uninstall(settings: Settings, remove_data: bool = True) -> None:
    if sys.platform == "darwin":
        import os
        import subprocess

        subprocess.run(
            ["/bin/launchctl", "bootout", f"gui/{os.getuid()}/com.privacyguardian.app"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        for folder in manifest_locations().values():
            (folder / f"{HOST_NAME}.json").unlink(missing_ok=True)
        (Path.home() / "Library/LaunchAgents/com.privacyguardian.app.plist").unlink(missing_ok=True)
    elif sys.platform == "win32":
        winreg = importlib.import_module("winreg")
        for vendor in (
            "Google\\Chrome",
            "Microsoft\\Edge",
            "BraveSoftware\\Brave-Browser",
            "Mozilla",
        ):
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteKey(
                    winreg.HKEY_CURRENT_USER, rf"Software\{vendor}\NativeMessagingHosts\{HOST_NAME}"
                )
        from privacy_guardian.sensors.platform.windows import WindowsRegistry

        WindowsRegistry().set_autostart(None)
    if remove_data and settings.data_dir.is_dir() and settings.data_dir.name != "":
        # Only known product artifacts are deleted; never recursively delete arbitrary configured roots.
        for name in (
            "settings.toml",
            "ipc.token",
            "guardian.lock",
            "control.sock",
            "guardian.sqlite3",
            "guardian.sqlite3-wal",
            "guardian.sqlite3-shm",
            "install-manifest.json",
            "privacy-guardian-host",
        ):
            (settings.data_dir / name).unlink(missing_ok=True)
        for folder_name in ("chrome", "edge", "brave", "firefox", "logs"):
            target = settings.data_dir / folder_name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
        with contextlib.suppress(OSError):
            settings.data_dir.rmdir()
