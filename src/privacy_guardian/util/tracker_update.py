from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

import httpx

CATALOGUE_URL = "https://api.github.com/repos/duckduckgo/tracker-radar/git/trees/main?recursive=1"


def update_tracker_list(target: Path) -> int:
    """Fetch only after an explicit user action; preserve the previous list on failure."""
    data = bytearray()
    with httpx.stream(
        "GET",
        CATALOGUE_URL,
        timeout=25,
        follow_redirects=False,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PrivacyGuardian-tracker-update",
        },
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > 20 * 1024 * 1024:
                break
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Tracker catalogue exceeds size limit")
    catalogue = json.loads(data)
    if not isinstance(catalogue, dict) or catalogue.get("truncated"):
        raise ValueError("Incomplete tracker catalogue")
    domains = sorted(
        {
            item["path"].removeprefix("domains/US/").removesuffix(".json")
            for item in catalogue.get("tree", [])
            if isinstance(item, dict)
            and re.fullmatch(r"domains/US/[a-z0-9.-]+\.json", str(item.get("path", "")))
        }
    )
    if not 100 <= len(domains) <= 100_000:
        raise ValueError("Unexpected tracker catalogue size")
    value = {
        "source": "DuckDuckGo Tracker Radar",
        "source_url": CATALOGUE_URL,
        "license": "CC-BY-NC-SA-4.0",
        "copyright": "Copyright 2020 Duck Duck Go, Inc.",
        "domains": domains,
    }
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".trackers-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return len(domains)
