from __future__ import annotations

import sys

from privacy_guardian.sensors.platform.base import PlatformAdapter


def create_adapter() -> PlatformAdapter:
    if sys.platform == "darwin":
        from privacy_guardian.sensors.platform.macos import MacOSAdapter

        return MacOSAdapter()
    if sys.platform == "win32":
        from privacy_guardian.sensors.platform.windows import WindowsAdapter

        return WindowsAdapter()
    raise RuntimeError("Privacy Guardian supports macOS and Windows")
