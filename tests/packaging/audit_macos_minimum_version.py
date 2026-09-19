from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MACH_O_MAGICS = {
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
MINIMUM_PATTERN = re.compile(r"^(?:minos|version)\s+([0-9]+(?:\.[0-9]+){1,2})$")


@dataclass(frozen=True)
class MachOSlice:
    path: Path
    architecture: str
    minimum_version: tuple[int, ...]


def version_tuple(value: str) -> tuple[int, ...]:
    parts = tuple(int(part) for part in value.split("."))
    return (parts + (0, 0, 0))[:3]


def format_version(value: tuple[int, ...]) -> str:
    normalized = (value + (0, 0, 0))[:3]
    return ".".join(map(str, normalized[:2] if normalized[2] == 0 else normalized))


def is_mach_o(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACH_O_MAGICS
    except OSError:
        return False


def architectures(path: Path) -> list[str]:
    result = subprocess.run(
        ["lipo", "-archs", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    values = result.stdout.strip().split()
    if not values:
        raise RuntimeError(f"lipo reported no architectures for {path}")
    return values


def minimum_version(path: Path, architecture: str) -> tuple[int, ...]:
    result = subprocess.run(
        ["otool", "-arch", architecture, "-l", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    versions: list[tuple[int, ...]] = []
    command = ""
    for line in result.stdout.splitlines():
        value = line.strip()
        if value.startswith("cmd "):
            command = value.removeprefix("cmd ")
            continue
        match = MINIMUM_PATTERN.match(value)
        if match and (
            (command == "LC_BUILD_VERSION" and value.startswith("minos "))
            or (command == "LC_VERSION_MIN_MACOSX" and value.startswith("version "))
        ):
            versions.append(version_tuple(match.group(1)))
    if not versions:
        raise RuntimeError(f"no macOS minimum-version load command in {path} ({architecture})")
    return max(versions)


def audit_bundle(bundle: Path, maximum: tuple[int, ...] = (13, 0, 0)) -> list[MachOSlice]:
    if not bundle.is_dir():
        raise FileNotFoundError(f"application bundle not found: {bundle}")
    mach_o_files = sorted(path for path in bundle.rglob("*") if is_mach_o(path))
    if not mach_o_files:
        raise RuntimeError(f"no Mach-O files found in {bundle}")
    slices = [
        MachOSlice(path, architecture, minimum_version(path, architecture))
        for path in mach_o_files
        for architecture in architectures(path)
    ]
    incompatible = [item for item in slices if item.minimum_version > maximum]
    if incompatible:
        lines = [
            f"{item.path} [{item.architecture}] requires macOS {format_version(item.minimum_version)}"
            for item in incompatible
        ]
        raise RuntimeError(
            f"{len(incompatible)} Mach-O slice(s) exceed macOS {format_version(maximum)}:\n"
            + "\n".join(lines)
        )
    return slices


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit every Mach-O slice in an application bundle for macOS compatibility."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--maximum-minimum-version", default="13.0")
    arguments = parser.parse_args()
    maximum = version_tuple(arguments.maximum_minimum_version)
    slices = audit_bundle(arguments.bundle.resolve(), maximum)
    files = len({item.path for item in slices})
    highest = max(item.minimum_version for item in slices)
    print(
        f"audited {len(slices)} Mach-O slices in {files} files; "
        f"highest minimum macOS version is {format_version(highest)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
