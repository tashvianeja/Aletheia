from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from aletheia.core.events import Requester
from aletheia.engine.necessity import purposes


class PurposeResult(BaseModel):
    purpose: str = "unknown"
    confidence: float = Field(default=0.0, ge=0, le=1)
    source: str = "insufficient_signals"


@lru_cache(maxsize=1)
def known_sites() -> dict[str, dict[str, object]]:
    value: dict[str, dict[str, object]] = json.loads(
        files("aletheia.data").joinpath("known_sites.yaml").read_text()
    )
    return value


_KEYWORDS: dict[str, str] = {
    "image_tool": r"image.?compress|compress.?image|resize.?image|image.?resiz|png.?compress|jpeg.?compress",
    "file_converter": r"pdf.?convert|file.?convert|convert.?pdf|pdf.?compress|convert.?file",
    "government": r"visa.?portal|government|passport.?application|immigration|official.?tax",
    "banking": r"\bbank\b|banking|bank.?kyc|open.?bank.?account",
    "healthcare_provider": r"hospital|clinic|patient.?portal|healthcare",
    "free_download": r"free.?pdf.?download|download.?free.?pdf|free.?ebook|free.?download",
    "social": r"social.?photo|social.?network|share.?photos|social.?media",
    "recipe": r"\brecipe|cooking|cookbook|meal.?ideas",
    "wallpaper_utility": r"wallpaper",
    "backup": r"\bbackup\b|back.?up.?files",
    "screen_recorder": r"screen.?record|screen.?capture|screencast|\bobs\b",
    "password_manager": r"password.?manager|password.?vault|bitwarden|1password|keepass",
    "video_conference": r"video.?conferenc|video.?meeting|zoom|webex",
    "developer_tool": r"developer|\bide\b|code.?editor|github|gitlab",
    "saas_b2b": r"crm|project.?management|business.?software|team.?workspace|saas",
    "ecommerce": r"online.?shop|shopping|checkout|buy.?now|ecommerce",
    "news": r"news|journalism|headlines",
    "maps_navigation": r"navigation|directions|maps",
    "vpn": r"\bvpn\b|virtual.?private.?network",
    "accessibility_tool": r"screen.?reader|accessibility|voice.?control",
    "antivirus": r"antivirus|anti.?malware|security.?scanner",
}


def infer_purpose(
    origin: str = "",
    title: str = "",
    meta: str = "",
    headings: list[str] | None = None,
    cta: str = "",
    url_path: str = "",
    app_name: str = "",
    bundle_id: str = "",
    publisher: str = "",
) -> PurposeResult:
    host = (
        (urlsplit(origin if "://" in origin else "//" + origin).hostname or "").lower().rstrip(".")
    )
    sites = known_sites()
    # Only match complete DNS label suffixes; paypal.com.evil.example cannot inherit identity.
    labels = host.split(".")
    for offset in range(max(1, len(labels) - 1)):
        candidate = ".".join(labels[offset:])
        if candidate in sites:
            return PurposeResult(
                purpose=str(sites[candidate]["purpose"]), confidence=0.95, source="curated_domain"
            )
    text = " ".join(
        (title, meta, " ".join(headings or []), cta, url_path, app_name, bundle_id, publisher, host)
    ).lower()
    scored = [
        (len(re.findall(pattern, text, re.I)), purpose) for purpose, pattern in _KEYWORDS.items()
    ]
    scored.sort(reverse=True)
    if scored and scored[0][0]:
        count, purpose = scored[0]
        return PurposeResult(
            purpose=purpose, confidence=min(0.9, 0.65 + count * 0.08), source="local_signals"
        )
    for purpose in purposes():
        if purpose.replace("_", " ") in text:
            return PurposeResult(purpose=purpose, confidence=0.65, source="category_metadata")
    return PurposeResult()


def enrich_requester(requester: Requester, **signals: str) -> Requester:
    if requester.purpose != "unknown" and requester.purpose_confidence > 0:
        return requester.model_copy()
    result = infer_purpose(
        origin=requester.origin,
        app_name=requester.display_name,
        bundle_id=requester.bundle_id,
        title=signals.get("title", ""),
        meta=signals.get("meta", ""),
        cta=signals.get("cta", ""),
        url_path=signals.get("url_path", ""),
    )
    return requester.model_copy(
        update={"purpose": result.purpose, "purpose_confidence": result.confidence}
    )
