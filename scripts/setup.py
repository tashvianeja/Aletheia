from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    if not shutil.which("tesseract"):
        print(
            "Tesseract is missing. Install with brew install tesseract or winget install UB-Mannheim.TesseractOCR."
        )
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    subprocess.run([sys.executable, "scripts/generate_schema.py"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
