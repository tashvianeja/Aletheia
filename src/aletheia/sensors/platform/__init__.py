from __future__ import annotations

import sys

from aletheia.sensors.platform.base import PlatformAdapter


def create_adapter() -> PlatformAdapter:
    if sys.platform == "darwin":
        from aletheia.sensors.platform.macos import MacOSAdapter

        return MacOSAdapter()
    if sys.platform == "win32":
        from aletheia.sensors.platform.windows import WindowsAdapter

        return WindowsAdapter()
    raise RuntimeError("Aletheia supports macOS and Windows")
