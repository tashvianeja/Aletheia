from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.packaging.audit_macos_minimum_version import (
    MACH_O_MAGICS,
    audit_bundle,
    is_mach_o,
    minimum_version,
)


def test_mach_o_detection_uses_magic_and_ignores_symlinks(tmp_path: Path) -> None:
    binary = tmp_path / "extension.so"
    binary.write_bytes(next(iter(MACH_O_MAGICS)) + b"synthetic")
    link = tmp_path / "linked.dylib"
    link.symlink_to(binary)

    assert is_mach_o(binary)
    assert not is_mach_o(link)


def test_minimum_version_reads_build_and_legacy_load_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "PrivacyGuardian"
    binary.write_bytes(b"\xcf\xfa\xed\xfe")

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            stdout="cmd LC_VERSION_MIN_MACOSX\n  version 12.0\ncmd LC_BUILD_VERSION\n    minos 13.0\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert minimum_version(binary, "arm64") == (13, 0, 0)


def test_version_components_are_normalized_for_comparison() -> None:
    from tests.packaging.audit_macos_minimum_version import version_tuple

    assert version_tuple("13.0") == version_tuple("13.0.0")


def test_audit_reports_every_incompatible_architecture_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "PrivacyGuardian.app"
    first = app / "Contents/MacOS/PrivacyGuardian"
    second = app / "Contents/Frameworks/PySide6/QtCore.abi3.so"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"\xcf\xfa\xed\xfe")
    second.write_bytes(b"\xca\xfe\xba\xbe")
    monkeypatch.setattr(
        "tests.packaging.audit_macos_minimum_version.architectures",
        lambda path: ["arm64"] if path == first else ["arm64", "x86_64"],
    )
    versions = {
        (first, "arm64"): (12, 0),
        (second, "arm64"): (15, 0),
        (second, "x86_64"): (14, 0),
    }
    monkeypatch.setattr(
        "tests.packaging.audit_macos_minimum_version.minimum_version",
        lambda path, architecture: versions[(path, architecture)],
    )

    with pytest.raises(RuntimeError) as error:
        audit_bundle(app, (13, 0))

    message = str(error.value)
    assert "2 Mach-O slice(s)" in message
    assert "QtCore.abi3.so [arm64] requires macOS 15.0" in message
    assert "QtCore.abi3.so [x86_64] requires macOS 14.0" in message
