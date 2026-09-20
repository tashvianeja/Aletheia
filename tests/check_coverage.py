from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CORE_PREFIXES = (
    "aletheia/core/",
    "aletheia/analysis/pii/",
    "aletheia/detectors/",
    "aletheia/engine/",
    "aletheia/storage/",
)


def line_counts(files: dict[str, Any], prefixes: tuple[str, ...] | None = None) -> tuple[int, int]:
    covered = total = 0
    for raw_path, detail in files.items():
        path = raw_path.replace("\\", "/")
        if prefixes is not None and not any(prefix in path for prefix in prefixes):
            continue
        summary = detail["summary"]
        total += int(summary["num_statements"])
        covered += int(summary["covered_lines"])
    return covered, total


def percentage(counts: tuple[int, int]) -> float:
    covered, total = counts
    if total == 0:
        raise ValueError("coverage report did not contain any matching statements")
    return covered * 100.0 / total


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce Aletheia line-coverage gates")
    parser.add_argument("coverage_json", type=Path, nargs="?", default=Path("coverage.json"))
    parser.add_argument("--core-min", type=float, default=85.0)
    parser.add_argument("--overall-min", type=float, default=70.0)
    arguments = parser.parse_args()
    report = json.loads(arguments.coverage_json.read_text(encoding="utf-8"))
    files = report.get("files", {})
    core_counts = line_counts(files, CORE_PREFIXES)
    overall_counts = line_counts(files)
    try:
        core = percentage(core_counts)
        overall = percentage(overall_counts)
    except ValueError as error:
        print(f"coverage gate error: {error}")
        return 2
    print(
        f"core/detectors/engine/storage: {core:.2f}% "
        f"({core_counts[0]}/{core_counts[1]} lines; required {arguments.core_min:.2f}%)"
    )
    print(
        f"overall: {overall:.2f}% "
        f"({overall_counts[0]}/{overall_counts[1]} lines; required {arguments.overall_min:.2f}%)"
    )
    return int(core + 1e-12 < arguments.core_min or overall + 1e-12 < arguments.overall_min)


if __name__ == "__main__":
    raise SystemExit(main())
