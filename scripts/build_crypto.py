"""Build current cryptography with a macOS 13-compatible static OpenSSL on Intel."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.5.8"
SHA256 = "a8f84a39918ec6415ce765d9b429d313ba97b8143169c172e734b9514464f5b2"


def main() -> None:
    if sys.platform != "darwin" or platform.machine() != "x86_64":
        return
    import cryptography.hazmat.bindings._rust as bindings

    linked = subprocess.check_output(["otool", "-L", bindings.__file__], text=True)
    if "libssl.3.dylib" not in linked and "libcrypto.3.dylib" not in linked:
        return
    build = ROOT / "build/crypto13"
    build.mkdir(parents=True, exist_ok=True)
    archive = build / f"openssl-{VERSION}.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(
            f"https://www.openssl.org/source/openssl-{VERSION}.tar.gz", timeout=60
        ) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("OpenSSL source checksum mismatch")
    source = build / f"openssl-{VERSION}"
    prefix = build / "installed"
    environment = os.environ.copy()
    environment.update(
        MACOSX_DEPLOYMENT_TARGET="13.0",
        CFLAGS="-mmacosx-version-min=13.0",
        OPENSSL_DIR=str(prefix),
        OPENSSL_STATIC="1",
    )
    if not (prefix / "lib/libcrypto.a").exists():
        if source.exists():
            shutil.rmtree(source)
        with tarfile.open(archive) as bundle:
            bundle.extractall(build, filter="data")
        subprocess.run(
            [
                "perl",
                "Configure",
                "darwin64-x86_64-cc",
                "no-shared",
                "no-module",
                "no-tests",
                f"--prefix={prefix}",
                "--libdir=lib",
                "-mmacosx-version-min=13.0",
            ],
            cwd=source,
            env=environment,
            check=True,
        )
        subprocess.run(
            ["make", f"-j{min(4, os.cpu_count() or 2)}"],
            cwd=source,
            env=environment,
            check=True,
        )
        subprocess.run(["make", "install_sw"], cwd=source, env=environment, check=True)
    version = importlib.metadata.version("cryptography")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--reinstall",
            "--no-cache",
            "--no-binary",
            "cryptography",
            f"cryptography=={version}",
        ],
        env=environment,
        check=True,
    )
    rebuilt = subprocess.check_output(["otool", "-L", bindings.__file__], text=True)
    if "libssl.3.dylib" in rebuilt or "libcrypto.3.dylib" in rebuilt:
        raise RuntimeError("cryptography still links an external OpenSSL after rebuilding")
    # Run in a new process so the old binding cannot mask a failed replacement.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from cryptography.hazmat.decrepit.ciphers.algorithms import ARC4; "
            "from cryptography.hazmat.primitives.ciphers import Cipher; "
            "assert Cipher(ARC4(b'0123456789abcdef'), mode=None).encryptor().update(b'PDF')",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
