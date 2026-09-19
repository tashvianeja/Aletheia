from __future__ import annotations

import argparse
from pathlib import Path

from privacy_guardian.config import data_directory
from privacy_guardian.util.tracker_update import update_tracker_list


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicitly update the local Tracker Radar list.")
    parser.add_argument("--output", type=Path, default=data_directory() / "trackers.json")
    args = parser.parse_args()
    count = update_tracker_list(args.output)
    print(f"Updated {count} tracker domains at {args.output}")


if __name__ == "__main__":
    main()
