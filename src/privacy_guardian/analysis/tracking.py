from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field

DECORATION_KEYS = frozenset(
    {
        "gclid",
        "fbclid",
        "msclkid",
        "dclid",
        "ttclid",
        "_ga",
        "mc_eid",
        "yclid",
        "gbraid",
        "wbraid",
        "igshid",
        "twclid",
    }
)


class CookieObservation(BaseModel):
    domain: str
    name: str = ""
    third_party: bool = False
    lifetime_days: float = 0


class TrackingSnapshot(BaseModel):
    origin: str = ""
    urls: list[str] = Field(default_factory=list)
    request_hosts: list[str] = Field(default_factory=list)
    cookies: list[CookieObservation] = Field(default_factory=list)
    api_calls: list[str] = Field(default_factory=list)
    fingerprinting: bool = False
    storage_shared_identifiers: int = 0
    cname_hosts: list[str] = Field(default_factory=list)
    pixel_beacons: int = 0
    pixel_hosts: list[str] = Field(default_factory=list)
    identity_sync: bool = False


class TrackingAnalysis(BaseModel):
    detected: bool = False
    tracker_domains: list[str] = Field(default_factory=list)
    fingerprinting: bool = False
    confidence: float = 0
    signals: list[str] = Field(default_factory=list)
    summary: str = "No persistent profiling signals found."


@lru_cache(maxsize=1)
def tracker_hosts() -> frozenset[str]:
    value = json.loads(files("privacy_guardian.data").joinpath("trackers.json").read_text())
    return frozenset(str(domain) for domain in value["domains"])


def is_tracker(host: str) -> bool:
    host = host.lower().lstrip(".").rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in tracker_hosts())


def analyze_tracking(snapshot: TrackingSnapshot | dict[str, object]) -> TrackingAnalysis:
    if not isinstance(snapshot, TrackingSnapshot):
        snapshot = TrackingSnapshot.model_validate(snapshot)
    result = TrackingAnalysis()
    hosts = set(snapshot.request_hosts + snapshot.cname_hosts)
    hosts.update(urlsplit(url).hostname or "" for url in snapshot.urls)
    trackers = {host.lower().lstrip(".") for host in hosts if is_tracker(host)}
    origin_host = urlsplit(snapshot.origin).hostname or ""
    for host in snapshot.pixel_hosts:
        if (
            host
            and host != origin_host
            and not host.endswith("." + origin_host)
            and any(
                (urlsplit(url).hostname or "") == host
                and (
                    "pixel" in urlsplit(url).path.lower()
                    or set(parse_qs(urlsplit(url).query)) & {"uid", "id", "cid", "email_hash"}
                )
                for url in snapshot.urls
            )
        ):
            trackers.add(host.lower())
    for cookie in snapshot.cookies:
        if cookie.third_party and cookie.lifetime_days >= 30 and is_tracker(cookie.domain):
            trackers.add(cookie.domain.lower().lstrip("."))
            if "persistent_third_party_cookies" not in result.signals:
                result.signals.append("persistent_third_party_cookies")
    if trackers:
        result.signals.append("known_tracker_requests")
    if any(set(parse_qs(urlsplit(url).query)) & DECORATION_KEYS for url in snapshot.urls):
        result.signals.append("url_decoration")
    calls = set(snapshot.api_calls)
    canvas = bool(calls & {"canvas.toDataURL", "canvas.getImageData", "toDataURL"}) and bool(
        calls & {"canvas.fillText", "canvas.drawImage", "canvas.draw", "fillText"}
    )
    audio = bool(calls & {"AudioContext", "OfflineAudioContext", "audio.analysis"}) and bool(
        calls & {"AnalyserNode", "getFloatFrequencyData", "audio.analysis"}
    )
    enumeration = (
        len(
            calls
            & {
                "navigator.plugins",
                "navigator.hardwareConcurrency",
                "navigator.deviceMemory",
                "WebGL.renderer",
                "font.enumeration",
            }
        )
        >= 3
    )
    result.fingerprinting = snapshot.fingerprinting or canvas or audio or enumeration
    if result.fingerprinting:
        result.signals.append("fingerprinting")
    if snapshot.storage_shared_identifiers > 0:
        result.signals.append("cross_origin_storage_identifier")
    if snapshot.cname_hosts and any(is_tracker(host) for host in snapshot.cname_hosts):
        result.signals.append("cname_cloaking")
    if snapshot.pixel_beacons > 0 and trackers:
        result.signals.append("tracking_pixels")
    if snapshot.identity_sync or any(
        re.search(
            r"(?:match|sync|identify).{0,30}(?:hash|email|uid)|(?:email_hash|hashed_email)=",
            url,
            re.I,
        )
        for url in snapshot.urls
    ):
        result.signals.append("identity_linking")
    result.tracker_domains = sorted(trackers)
    result.detected = bool(result.signals)
    result.confidence = (
        min(0.99, 0.35 + len(result.signals) * 0.12 + min(len(trackers), 4) * 0.05)
        if result.detected
        else 0
    )
    if result.detected:
        result.summary = (
            "This site appears to be using persistent identifiers to build an advertising profile."
        )
    return result
