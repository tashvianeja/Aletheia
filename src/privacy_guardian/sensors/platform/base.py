from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

from privacy_guardian.core.events import DataCategory, PrivacyEvent, Requester, SystemAccessEvent

Emit = Callable[[PrivacyEvent], None]

PERMISSION_CATEGORIES: dict[str, DataCategory] = {
    "camera": DataCategory.CAMERA,
    "microphone": DataCategory.MICROPHONE,
    "location": DataCategory.LOCATION_PRECISE,
    "contacts": DataCategory.CONTACTS,
    "calendar": DataCategory.CALENDAR,
    "photos": DataCategory.BIOMETRIC_PHOTO,
    "files": DataCategory.FILES_BROAD,
    "full_disk": DataCategory.FILES_BROAD,
    "accessibility": DataCategory.ACCESSIBILITY,
    "screen": DataCategory.SCREEN,
    "input_monitoring": DataCategory.ACCESSIBILITY,
    "automation": DataCategory.AUTOMATION,
    "notifications": DataCategory.DEVICE_IDENTIFIERS,
    "bluetooth": DataCategory.DEVICE_IDENTIFIERS,
    "startup": DataCategory.STARTUP,
    "background": DataCategory.BACKGROUND_EXECUTION,
    "browser_history": DataCategory.BROWSER_HISTORY,
}


class PlatformAdapter(ABC):
    @abstractmethod
    def start(self, emit: Emit) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def permissions_status(self) -> dict[str, bool]: ...
    @abstractmethod
    def foreground_requester(self) -> Requester: ...
    @abstractmethod
    def snapshot(self, requester: Requester | None = None) -> list[PrivacyEvent]: ...
    @abstractmethod
    def open_settings(self, permission: str) -> None: ...
    @abstractmethod
    def set_autostart(self, enabled: bool) -> None: ...


def extension_event(manifest: dict[str, Any], identity: str = "") -> SystemAccessEvent | None:
    permissions = set(manifest.get("permissions", [])) | set(manifest.get("host_permissions", []))
    categories = []
    if "history" in permissions:
        categories.append(DataCategory.BROWSER_HISTORY)
    if "clipboardRead" in permissions:
        categories.append(DataCategory.CLIPBOARD)
    if permissions & {"tabs", "webRequest", "<all_urls>"}:
        categories.append(DataCategory.BROWSING_ACTIVITY)
    if not categories:
        return None
    return SystemAccessEvent(
        source="os",
        requester=Requester(
            kind="extension",
            bundle_id=identity,
            display_name=str(manifest.get("name", "Browser extension")),
        ),
        data_categories=categories,
        accesses=sorted(
            permissions & {"history", "tabs", "<all_urls>", "webRequest", "clipboardRead"}
        ),
        breadth=min(
            1,
            len(permissions & {"history", "tabs", "<all_urls>", "webRequest", "clipboardRead"}) / 3,
        ),
    )


def scan_extension_manifests(roots: list[Path]) -> list[PrivacyEvent]:
    import json

    events: list[PrivacyEvent] = []
    for root in roots:
        if not root.exists():
            continue
        for manifest in root.glob("*/Extensions/*/*/manifest.json"):
            try:
                event = extension_event(
                    json.loads(manifest.read_text()), manifest.parent.parent.name
                )
                if event:
                    events.append(event)
            except (OSError, ValueError, TypeError):
                continue
        for profile in root.glob("*/extensions.json"):
            try:
                for addon in json.loads(profile.read_text()).get("addons", []):
                    permissions = addon.get("userPermissions", {})
                    event = extension_event(
                        {
                            "name": addon.get("defaultLocale", {}).get("name", "Browser extension"),
                            "permissions": permissions.get("permissions", []),
                            "host_permissions": permissions.get("origins", []),
                        },
                        addon.get("id", ""),
                    )
                    if event:
                        events.append(event)
            except (OSError, ValueError, TypeError):
                continue
    return events
