from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bundle_ocr() -> None:
    if sys.platform == "darwin":
        compatible = ROOT / "build/tesseract13"
        if not (compatible / "tesseract").exists():
            subprocess.run([sys.executable, str(ROOT / "scripts/build_ocr.py")], check=True)
        target = ROOT / "build/tesseract"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(compatible, target)
        return
    binary = shutil.which("tesseract")
    if not binary and sys.platform == "win32":
        candidate = (
            Path(os.getenv("PROGRAMFILES", r"C:\Program Files")) / "Tesseract-OCR/tesseract.exe"
        )
        if candidate.exists():
            binary = str(candidate)
    if not binary:
        raise RuntimeError("Tesseract must be installed before packaging")
    source = Path(binary).resolve()
    target = ROOT / "build/tesseract"
    target.mkdir(parents=True, exist_ok=True)
    existing_binary = target / source.name
    if existing_binary.exists():
        existing_binary.chmod(0o755)
    shutil.copy2(source, existing_binary)
    existing_binary.chmod(0o755)
    if sys.platform == "win32":
        for dll in source.parent.glob("*.dll"):
            shutil.copy2(dll, target / dll.name)
        traineddata = source.parent / "tessdata"
    else:
        traineddata = source.parent.parent / "share/tessdata"
        seen: set[str] = set()

        def dependencies(path: Path) -> None:
            listing = subprocess.check_output(["otool", "-L", str(path)], text=True)
            for line in listing.splitlines()[1:]:
                dependency = line.strip().split(" (", 1)[0]
                if dependency.startswith(("/usr/lib/", "/System/", "@")):
                    continue
                library = Path(dependency)
                if library.exists():
                    copied = target / library.name
                    if dependency not in seen:
                        seen.add(dependency)
                        if copied.exists():
                            copied.chmod(0o755)
                        shutil.copy2(library.resolve(), copied)
                        copied.chmod(0o755)
                        dependencies(copied)
                    subprocess.run(
                        [
                            "install_name_tool",
                            "-change",
                            dependency,
                            "@loader_path/" + library.name,
                            str(path),
                        ],
                        check=True,
                    )

        dependencies(target / source.name)
        for library in target.glob("*.dylib"):
            subprocess.run(
                ["install_name_tool", "-id", "@loader_path/" + library.name, str(library)],
                check=True,
            )
    (target / "tessdata").mkdir(exist_ok=True)
    for name in ("eng.traineddata", "osd.traineddata"):
        origin = traineddata / name
        if origin.exists():
            shutil.copy2(origin, target / "tessdata" / name)
    if not (target / "tessdata/eng.traineddata").exists():
        raise RuntimeError("Tesseract English language data is required")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=["mac", "windows"])
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if args.platform == "mac":
        subprocess.run([sys.executable, str(ROOT / "scripts/build_crypto.py")], check=True)
    bundle_ocr()
    spec = (
        ROOT
        / "packaging"
        / ("macos" if args.platform == "mac" else "windows")
        / "PrivacyGuardian.spec"
    )
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(spec)], cwd=ROOT, check=True
    )
    if args.platform == "mac":
        app = ROOT / "dist/PrivacyGuardian.app"
        identity = os.getenv("CODESIGN_IDENTITY", "-")
        subprocess.run(
            [
                "codesign",
                "--deep",
                "--force",
                "--sign",
                identity,
                *(["--options", "runtime", "--timestamp"] if identity != "-" else []),
                "--entitlements",
                str(ROOT / "packaging/macos/entitlements.plist"),
                str(app),
            ],
            check=True,
        )
        dmg = ROOT / f"dist/PrivacyGuardian-{version}.dmg"
        if dmg.exists():
            dmg.unlink()
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                "Privacy Guardian",
                "-srcfolder",
                str(app),
                "-ov",
                "-format",
                "UDZO",
                str(dmg),
            ],
            check=True,
        )
        if os.getenv("NOTARY_PROFILE"):
            subprocess.run(
                [
                    "xcrun",
                    "notarytool",
                    "submit",
                    str(dmg),
                    "--keychain-profile",
                    os.environ["NOTARY_PROFILE"],
                    "--wait",
                ],
                check=True,
            )
            subprocess.run(["xcrun", "stapler", "staple", str(dmg)], check=True)
        print(dmg)
    else:
        compiler = shutil.which("ISCC") or str(
            Path(os.getenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Inno Setup 6/ISCC.exe"
        )
        subprocess.run(
            [compiler, f"/DAppVersion={version}", str(ROOT / "packaging/windows/installer.iss")],
            check=True,
        )


if __name__ == "__main__":
    main()
