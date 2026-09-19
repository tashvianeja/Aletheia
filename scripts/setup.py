from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if not shutil.which("tesseract"):
        print(
            "Tesseract is missing. Install with brew install tesseract or winget install UB-Mannheim.TesseractOCR."
        )
    firefox = shutil.which("firefox") or next(
        (
            str(path)
            for path in (
                Path("/Applications/Firefox.app/Contents/MacOS/firefox"),
                Path("C:/Program Files/Mozilla Firefox/firefox.exe"),
            )
            if path.exists()
        ),
        None,
    )
    if not firefox:
        if sys.platform == "darwin" and shutil.which("brew"):
            subprocess.run(["brew", "install", "--cask", "firefox"], check=True)
        elif sys.platform == "win32" and shutil.which("winget"):
            subprocess.run(
                [
                    "winget",
                    "install",
                    "--id",
                    "Mozilla.Firefox",
                    "--exact",
                    "--silent",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ],
                check=True,
            )
        else:
            print(
                "Firefox is required for the browser native-host smoke test. Install Firefox, then rerun setup."
            )
            return 1
    npm = shutil.which("npm")
    if not npm:
        print("Node.js 20 or newer (including npm) is required for Firefox web-ext tests.")
        return 1
    subprocess.run(
        [npm, "install", "--prefix", "build/firefox-tools", "web-ext@10.6.0"], check=True
    )
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    subprocess.run([sys.executable, "scripts/generate_schema.py"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
