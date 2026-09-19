from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .audit_macos_minimum_version import audit_bundle, version_tuple
else:
    from audit_macos_minimum_version import audit_bundle, version_tuple

CHROME_ID = "bfdjphkbgihhbonhnmjbbfhckdddonob"
HOST_NAME = "com.privacyguardian.host"


@dataclass(frozen=True)
class FileState:
    path: Path
    content: bytes | None
    mode: int | None

    @classmethod
    def capture(cls, path: Path) -> FileState:
        if path.is_file() and not path.is_symlink():
            return cls(path, path.read_bytes(), path.stat().st_mode & 0o777)
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"refusing to replace non-regular user state: {path}")
        return cls(path, None, None)

    def restore(self) -> None:
        self.path.unlink(missing_ok=True)
        if self.content is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(self.content)
            if self.mode is not None:
                self.path.chmod(self.mode)


def macos_registration_paths() -> list[Path]:
    base = Path.home() / "Library/Application Support"
    return [
        base / vendor / "NativeMessagingHosts" / f"{HOST_NAME}.json"
        for vendor in ("Google/Chrome", "Microsoft Edge", "BraveSoftware/Brave-Browser", "Mozilla")
    ] + [Path.home() / "Library/LaunchAgents/com.privacyguardian.app.plist"]


@contextlib.contextmanager
def preserve_macos_user_state() -> Iterator[None]:
    parents = {
        parent
        for path in macos_registration_paths()
        for parent in path.parents
        if parent != Path.home() and not parent.exists()
    }
    states = [FileState.capture(path) for path in macos_registration_paths()]
    try:
        yield
    finally:
        for state in states:
            state.restore()
        for parent in sorted(parents, key=lambda item: len(item.parts), reverse=True):
            with contextlib.suppress(OSError):
                parent.rmdir()


def wait_for(path: Path, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {path}")


def run_checked(command: list[str], *, environment: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=environment, timeout=180)


def native_exchange(
    executable: Path,
    environment: dict[str, str],
    requests: list[dict[str, object]],
) -> list[dict[str, object]]:
    process = subprocess.Popen(
        [str(executable), f"chrome-extension://{CHROME_ID}/"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    responses: list[dict[str, object]] = []
    try:
        with ThreadPoolExecutor(max_workers=1) as reader:
            for request in requests:
                encoded = json.dumps(request, separators=(",", ":")).encode()
                process.stdin.write(struct.pack("<I", len(encoded)) + encoded)
                process.stdin.flush()
                try:
                    header = reader.submit(process.stdout.read, 4).result(timeout=30)
                    if len(header) != 4:
                        raise RuntimeError(f"native host returned a truncated header: {header!r}")
                    size = struct.unpack("<I", header)[0]
                    payload = reader.submit(process.stdout.read, size).result(timeout=30)
                except FutureTimeoutError as error:
                    process.kill()
                    raise TimeoutError("native host response timed out") from error
                if len(payload) != size:
                    raise RuntimeError(f"native host returned a truncated message: {payload!r}")
                responses.append(json.loads(payload))
        process.stdin.close()
        process.wait(timeout=30)
        if process.returncode:
            assert process.stderr is not None
            raise subprocess.CalledProcessError(
                process.returncode,
                process.args,
                stderr=process.stderr.read(),
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    return responses


def native_handshake(executable: Path, environment: dict[str, str]) -> dict[str, object]:
    response = native_exchange(
        executable,
        environment,
        [
            {
                "v": 1,
                "id": "packaged-handshake",
                "type": "ping",
                "payload": {"browser": "packaged-smoke"},
            }
        ],
    )[0]
    if not response.get("ok") or response.get("result", {}).get("status") != "ready":
        raise RuntimeError(f"native host handshake failed: {response}")
    return response


def unique_named_files(root: Path, names: set[str]) -> list[Path]:
    """Return physical files once when an app exposes them through resource symlinks."""
    return sorted(
        {path.resolve() for path in root.rglob("*") if path.is_file() and path.name.lower() in names}
    )


def verify_ocr(
    install_root: Path,
    native_host: Path,
    environment: dict[str, str],
    work_dir: Path,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    names = {"tesseract.exe"} if sys.platform == "win32" else {"tesseract"}
    binaries = unique_named_files(install_root, names)
    if len(binaries) != 1:
        raise RuntimeError(f"expected one bundled Tesseract executable, found {binaries}")
    traineddata = list(install_root.rglob("eng.traineddata"))
    if not traineddata:
        raise RuntimeError("bundled eng.traineddata is missing")
    image_path = work_dir / "synthetic-ocr.jpg"
    png_path = work_dir / "synthetic-ocr.png"
    image = Image.new("RGB", (1400, 260), "white")
    font = ImageFont.load_default(size=64)
    text = "SYNTHETIC OCR testperson@example.test"
    ImageDraw.Draw(image).text((40, 70), text, fill="black", font=font)
    image.save(image_path, format="JPEG", quality=95)
    image.save(png_path, format="PNG")
    ocr_environment = environment.copy()
    ocr_environment["TESSDATA_PREFIX"] = str(traineddata[0].parent)
    result = subprocess.run(
        [str(binaries[0]), str(png_path), "stdout", "-l", "eng"],
        check=True,
        capture_output=True,
        text=True,
        env=ocr_environment,
        timeout=30,
    )
    normalized = " ".join(result.stdout.upper().split())
    if "SYNTHETIC OCR" not in normalized or "TESTPERSON@EXAMPLE.TEST" not in normalized:
        raise RuntimeError(f"bundled OCR did not read the converted PNG: {result.stdout!r}")
    data = image_path.read_bytes()
    responses = native_exchange(
        native_host,
        environment,
        [
            {
                "v": 1,
                "id": "jpeg-start",
                "type": "file_start",
                "payload": {
                    "upload_id": "synthetic-jpeg",
                    "filename": image_path.name,
                    "size": len(data),
                    "mime": "image/jpeg",
                    "requester": {"origin": "https://ocr-smoke.example"},
                },
            },
            {
                "v": 1,
                "id": "jpeg-chunk",
                "type": "file_chunk",
                "payload": {
                    "upload_id": "synthetic-jpeg",
                    "sequence": 0,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            },
            {
                "v": 1,
                "id": "jpeg-finish",
                "type": "file_finish",
                "payload": {"upload_id": "synthetic-jpeg"},
            },
        ],
    )
    findings = responses[-1].get("result", {}).get("findings", [])
    if not any(item.get("category") == "email" for item in findings):
        raise RuntimeError(
            f"packaged JPEG analysis did not detect the synthetic email: {responses}"
        )


def visible_onboarding(app: Path, data_dir: Path, environment: dict[str, str]) -> None:
    (data_dir / "tray-ready").unlink(missing_ok=True)
    gui_environment = environment.copy()
    gui_environment.pop("QT_QPA_PLATFORM", None)
    process = subprocess.Popen(
        [str(app), "--no-autostart"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=gui_environment,
    )
    try:
        wait_for(data_dir / "tray-ready")
        deadline = time.monotonic() + 15
        observed = False
        while time.monotonic() < deadline and not observed:
            if sys.platform == "darwin":
                import Quartz

                windows = Quartz.CGWindowListCopyWindowInfo(
                    Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
                )
                observed = any(
                    window.get("kCGWindowOwnerPID") == process.pid
                    and window.get("kCGWindowLayer") == 0
                    and window.get("kCGWindowBounds", {}).get("Width", 0) >= 500
                    and window.get("kCGWindowBounds", {}).get("Height", 0) >= 350
                    for window in windows
                )
            elif sys.platform == "win32":
                import ctypes
                import ctypes.wintypes

                found: list[int] = []
                user32 = ctypes.windll.user32
                callback_type = ctypes.WINFUNCTYPE(
                    ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
                )
                user32.GetWindowThreadProcessId.argtypes = [
                    ctypes.wintypes.HWND,
                    ctypes.POINTER(ctypes.wintypes.DWORD),
                ]
                user32.GetWindowRect.argtypes = [
                    ctypes.wintypes.HWND,
                    ctypes.POINTER(ctypes.wintypes.RECT),
                ]
                user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
                user32.EnumWindows.argtypes = [callback_type, ctypes.wintypes.LPARAM]

                @callback_type
                def visit(
                    window: int,
                    _context: int,
                    _user32: object = user32,
                    _found: list[int] = found,
                ) -> bool:
                    owner = ctypes.c_ulong()
                    _user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
                    rectangle = ctypes.wintypes.RECT()
                    _user32.GetWindowRect(window, ctypes.byref(rectangle))
                    if (
                        owner.value == process.pid
                        and _user32.IsWindowVisible(window)
                        and rectangle.right - rectangle.left >= 500
                        and rectangle.bottom - rectangle.top >= 350
                    ):
                        _found.append(window)
                    return True

                user32.EnumWindows(visit, 0)
                observed = bool(found)
            if not observed:
                time.sleep(0.2)
        if not observed:
            raise RuntimeError("fresh packaged launch did not expose the onboarding window")
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def verify_runtime(
    app: Path,
    native_host: Path,
    install_root: Path,
    data_dir: Path,
    work_dir: Path,
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PRIVACY_GUARDIAN_DATA_DIR"] = str(data_dir)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    run_checked([str(app), "--smoke-test", "--no-autostart"], environment=environment)
    wait_for(data_dir / "tray-ready")
    settings = tomllib.loads((data_dir / "settings.toml").read_text(encoding="utf-8"))
    if settings.get("onboarding_complete", False) is not False:
        raise RuntimeError("fresh packaged profile unexpectedly bypasses onboarding")
    visible_onboarding(app, data_dir, environment)
    service = subprocess.Popen(
        [str(app), "--headless", "--no-autostart"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
    )
    try:
        wait_for(data_dir / "ipc.token")
        deadline = time.monotonic() + 30
        while True:
            try:
                response = native_handshake(native_host, environment)
                break
            except (OSError, subprocess.SubprocessError, RuntimeError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        verify_ocr(install_root, native_host, environment, work_dir)
    finally:
        service.terminate()
        try:
            service.wait(timeout=10)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait(timeout=5)
    return response


def verify_macos(artifact: Path, work_dir: Path, maximum_macos: str) -> None:
    install_dir = work_dir / "Applications"
    install_dir.mkdir()
    mounted: Path | None = None
    try:
        if artifact.suffix == ".dmg":
            mounted = work_dir / "mounted-dmg"
            mounted.mkdir()
            run_checked(
                [
                    "hdiutil",
                    "attach",
                    "-nobrowse",
                    "-readonly",
                    "-mountpoint",
                    str(mounted),
                    str(artifact),
                ]
            )
            source = mounted / "PrivacyGuardian.app"
        else:
            source = artifact
        installed = install_dir / "PrivacyGuardian.app"
        run_checked(["ditto", str(source), str(installed)])
        run_checked(["codesign", "--verify", "--deep", "--strict", str(installed)])
        audit_bundle(installed, version_tuple(maximum_macos))
        app = installed / "Contents/MacOS/PrivacyGuardian"
        data_dir = work_dir / "profile"
        environment = os.environ.copy()
        environment["PRIVACY_GUARDIAN_DATA_DIR"] = str(data_dir)
        with preserve_macos_user_state():
            installed_registration = False
            try:
                run_checked(
                    [str(app), "--install-native-host", "--no-autostart"],
                    environment=environment,
                )
                installed_registration = True
                manifests = macos_registration_paths()[:-1]
                for manifest in manifests:
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    if not Path(payload["path"]).is_file():
                        raise RuntimeError(f"manifest host path is missing: {manifest}")
                host = Path(json.loads(manifests[0].read_text(encoding="utf-8"))["path"])
                response = verify_runtime(app, host, installed, data_dir, work_dir)
            finally:
                if installed_registration:
                    subprocess.run(
                        [str(app), "--uninstall"],
                        check=False,
                        env=environment,
                        timeout=30,
                    )
            leftovers = [path for path in manifests if path.exists()]
            if leftovers:
                raise RuntimeError(f"uninstall left native-host registrations: {leftovers}")
            known = [
                data_dir / name
                for name in ("settings.toml", "ipc.token", "tray-ready", "guardian.sqlite3")
            ]
            if any(path.exists() for path in known):
                raise RuntimeError(
                    f"uninstall left known profile files: {[p for p in known if p.exists()]}"
                )
        print(f"macOS packaged lifecycle passed; native response={response['result']}")
    finally:
        if mounted is not None:
            subprocess.run(["hdiutil", "detach", str(mounted)], check=False, timeout=30)


def registry_key_exists(path: str) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return key is not None
    except FileNotFoundError:
        return False


def registry_value(path: str, name: str) -> tuple[bool, bool, object, int]:
    import winreg

    key_existed = registry_key_exists(path)
    if key_existed:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            try:
                value, kind = winreg.QueryValueEx(key, name)
                return True, True, value, kind
            except FileNotFoundError:
                pass
    return key_existed, False, "", winreg.REG_NONE


def restore_registry_value(path: str, name: str, state: tuple[bool, bool, object, int]) -> None:
    import winreg

    key_existed, value_existed, value, kind = state
    if key_existed:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            if value_existed:
                winreg.SetValueEx(key, name, 0, kind, value)
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, name)
    else:
        with contextlib.suppress(FileNotFoundError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def verify_windows(installer: Path, work_dir: Path) -> None:
    registry_paths = [
        rf"Software\{vendor}\NativeMessagingHosts\{HOST_NAME}"
        for vendor in (
            r"Google\Chrome",
            r"Microsoft\Edge",
            r"BraveSoftware\Brave-Browser",
            "Mozilla",
        )
    ]
    states = {(path, ""): registry_value(path, "") for path in registry_paths}
    run_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    states[(run_path, "PrivacyGuardian")] = registry_value(run_path, "PrivacyGuardian")
    install_dir = work_dir / "installed"
    data_dir = work_dir / "profile"
    environment = os.environ.copy()
    environment["PRIVACY_GUARDIAN_DATA_DIR"] = str(data_dir)
    uninstaller: Path | None = None
    try:
        run_checked(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                "/MERGETASKS=!autostart",
                f"/DIR={install_dir}",
            ],
            environment=environment,
        )
        app = install_dir / "PrivacyGuardian.exe"
        host = install_dir / "PrivacyGuardianHost.exe"
        if not app.is_file() or not host.is_file():
            raise RuntimeError(
                f"silent installer did not create packaged executables in {install_dir}"
            )
        response = verify_runtime(app, host, install_dir, data_dir, work_dir)
        uninstallers = list(install_dir.glob("unins*.exe"))
        if len(uninstallers) != 1:
            raise RuntimeError(f"expected one Inno Setup uninstaller, found {uninstallers}")
        uninstaller = uninstallers[0]
        run_checked(
            [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            environment=environment,
        )
        if app.exists() or host.exists():
            raise RuntimeError("Windows uninstaller left packaged executables behind")
        if any(registry_value(path, "")[0] for path in registry_paths):
            raise RuntimeError("Windows uninstaller left native-host registrations behind")
        print(f"Windows packaged lifecycle passed; native response={response['result']}")
    finally:
        if uninstaller is None:
            candidates = list(install_dir.glob("unins*.exe"))
            uninstaller = candidates[0] if len(candidates) == 1 else None
        if uninstaller is not None and uninstaller.exists():
            subprocess.run(
                [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                check=False,
                env=environment,
                timeout=180,
            )
        for (path, name), state in states.items():
            restore_registry_value(path, name, state)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a packaged Privacy Guardian install lifecycle."
    )
    parser.add_argument("--platform", choices=("macos", "windows"), required=True)
    parser.add_argument(
        "--artifact", type=Path, required=True, help="macOS .app/.dmg or Windows setup .exe"
    )
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--maximum-macos", default="13.0")
    arguments = parser.parse_args()
    artifact = arguments.artifact.resolve()
    if not artifact.exists():
        parser.error(f"artifact does not exist: {artifact}")
    with (
        tempfile.TemporaryDirectory(prefix="pg-packaged-")
        if arguments.work_dir is None
        else contextlib.nullcontext(str(arguments.work_dir)) as raw_work_dir
    ):
        work_dir = Path(raw_work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        if arguments.platform == "macos":
            verify_macos(artifact, work_dir, arguments.maximum_macos)
        else:
            verify_windows(artifact, work_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
