from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/ocr-source"
PREFIX = WORK / "install"


def source(name: str, url: str) -> Path:
    target = WORK / name
    if target.exists():
        return target
    archive = WORK / f"{name}.tar.gz"
    urllib.request.urlretrieve(url, archive)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        top = members[0].name.split("/")[0]
        bundle.extractall(WORK, filter="data")
    (WORK / top).rename(target)
    return target


def build(name: str, url: str, options: list[str]) -> None:
    src = source(name, url)
    output = WORK / (name + "-build")
    common = [
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={PREFIX}",
        f"-DCMAKE_PREFIX_PATH={PREFIX}",
        "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local",
    ]
    subprocess.run(["cmake", "-S", str(src), "-B", str(output), *common, *options], check=True)
    subprocess.run(
        ["cmake", "--build", str(output), "--parallel", str(min(os.cpu_count() or 2, 8))],
        check=True,
    )
    subprocess.run(["cmake", "--install", str(output)], check=True)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    build(
        "libpng",
        "https://github.com/pnggroup/libpng/archive/refs/tags/v1.6.58.tar.gz",
        [
            "-DPNG_SHARED=OFF",
            "-DPNG_FRAMEWORK=OFF",
            "-DPNG_STATIC=ON",
            "-DPNG_TESTS=OFF",
            "-DPNG_TOOLS=OFF",
        ],
    )
    build(
        "leptonica",
        "https://github.com/DanBloomberg/leptonica/archive/refs/tags/1.87.0.tar.gz",
        [
            "-DBUILD_PROG=OFF",
            "-DENABLE_PNG=ON",
            f"-DPNG_LIBRARY={PREFIX}/lib/libpng16.a",
            f"-DPNG_PNG_INCLUDE_DIR={PREFIX}/include",
            "-DENABLE_JPEG=OFF",
            "-DENABLE_TIFF=OFF",
            "-DENABLE_GIF=OFF",
            "-DENABLE_WEBP=OFF",
            "-DENABLE_OPENJPEG=OFF",
        ],
    )
    build(
        "tesseract",
        "https://github.com/tesseract-ocr/tesseract/archive/refs/tags/5.5.3.tar.gz",
        [
            "-DBUILD_TRAINING_TOOLS=OFF",
            "-DBUILD_TESTS=OFF",
            "-DDISABLE_ARCHIVE=ON",
            "-DDISABLE_CURL=ON",
            "-DDISABLE_TIFF=ON",
            "-DDISABLED_LEGACY_ENGINE=ON",
            "-DOPENMP_BUILD=OFF",
            "-DGRAPHICS_DISABLED=ON",
            "-DENABLE_NATIVE=OFF",
        ],
    )
    output = ROOT / "build/tesseract13"
    output.mkdir(exist_ok=True)
    shutil.copy2(PREFIX / "bin/tesseract", output / "tesseract")
    (output / "tessdata").mkdir(exist_ok=True)
    installed = Path(shutil.which("tesseract") or "").resolve().parent.parent / "share/tessdata"
    for name in ("eng.traineddata", "osd.traineddata"):
        if (installed / name).exists():
            shutil.copy2(installed / name, output / "tessdata" / name)
    subprocess.run(["codesign", "--force", "--sign", "-", str(output / "tesseract")], check=True)
    subprocess.run(["otool", "-L", str(output / "tesseract")], check=True)
    subprocess.run(["xcrun", "vtool", "-show-build", str(output / "tesseract")], check=True)


if __name__ == "__main__":
    main()
