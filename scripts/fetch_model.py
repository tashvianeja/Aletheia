"""Fetch the on-device sentence encoder used to judge what a form is for.

The weights are a build input rather than source, so they are downloaded and checksummed
here instead of being committed. Privacy Guardian degrades to structural-only inference
when they are absent, so a failed fetch weakens the judgement but never breaks the app.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/privacy_guardian/data/models"
BASE = "https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/main"
FILES = {
    "minilm-int8.onnx": (
        f"{BASE}/onnx/model_quantized.onnx",
        "afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1",
    ),
    "vocab.txt": (
        f"{BASE}/vocab.txt",
        "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    ),
}


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in FILES.items():
        path = TARGET / name
        if path.exists() and digest(path) == expected:
            print(f"{name}: present")
            continue
        print(f"{name}: downloading")
        urllib.request.urlretrieve(url, path)
        actual = digest(path)
        if actual != expected:
            path.unlink(missing_ok=True)
            print(f"{name}: checksum mismatch ({actual})", file=sys.stderr)
            return 1
        print(f"{name}: {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
