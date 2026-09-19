import os
import sys
from pathlib import Path

root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
ocr = root / "tesseract"
if ocr.exists():
    os.environ["PATH"] = str(ocr) + os.pathsep + os.environ.get("PATH", "")
    os.environ["TESSDATA_PREFIX"] = str(ocr / "tessdata")
