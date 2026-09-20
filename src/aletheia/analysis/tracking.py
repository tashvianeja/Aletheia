from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
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


@lru_cache(maxsize=8)
def _tracker_hosts(path: str, modified: int) -> frozenset[str]:
    del modified
    try:
        value = json.loads(Path(path).read_text()) if path else {}
        domains = value.get("domains", [])
        if not isinstance(domains, list) or not 100 <= len(domains) <= 100_000:
            raise ValueError("Invalid cached tracker list")
        if not all(
            isinstance(domain, str) and re.fullmatch(r"[a-z0-9.-]+", domain) for domain in domains
        ):
            raise ValueError("Invalid tracker domain")
    except (OSError, ValueError):
        value = json.loads(files("aletheia.data").joinpath("trackers.json").read_text())
    return frozenset(str(domain) for domain in value["domains"])


def tracker_hosts(path: str = "") -> frozenset[str]:
    if not path:
        from aletheia.config import data_directory

        path = str(data_directory() / "trackers.json")
    try:
        modified = Path(path).stat().st_mtime_ns
    except OSError:
        modified = 0
    return _tracker_hosts(path, modified)


def is_tracker(host: str, tracker_path: str = "") -> bool:
    labels = host.lower().lstrip(".").rstrip(".").split(".")
    domains = tracker_hosts(tracker_path)
    return any(".".join(labels[index:]) in domains for index in range(len(labels)))


# Where a two-label domain would cut into the public suffix rather than the name.
COMPOUND_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "co.jp",
        "co.kr",
        "co.nz",
        "co.za",
        "co.in",
        "com.au",
        "net.au",
        "com.br",
        "com.mx",
        "com.sg",
        "com.tr",
    }
)


def tracker_domain(host: str, tracker_path: str = "") -> str:
    """Name the company behind a host: doubleclick.net for cm.g.doubleclick.net.

    One advertising company reaches a page under a handful of hostnames, some of
    them a hash with a domain after it. Counted as hostnames they read as eleven
    separate websites following you, which is both alarming and wrong; counted as
    companies they read as the four it actually is.
    """
    labels = host.lower().strip(".").split(".")
    domains = tracker_hosts(tracker_path)
    for index in range(len(labels)):
        candidate = ".".join(labels[index:])
        if candidate in domains:
            return candidate
    if len(labels) > 2 and ".".join(labels[-2:]) in COMPOUND_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) > 2 else ".".join(labels)


def analyze_tracking(
    snapshot: TrackingSnapshot | dict[str, object], tracker_path: str = ""
) -> TrackingAnalysis:
    if not isinstance(snapshot, TrackingSnapshot):
        snapshot = TrackingSnapshot.model_validate(snapshot)
    result = TrackingAnalysis()
    hosts = set(snapshot.request_hosts + snapshot.cname_hosts)
    hosts.update(urlsplit(url).hostname or "" for url in snapshot.urls)
    trackers = {host.lower().lstrip(".") for host in hosts if is_tracker(host, tracker_path)}
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
        if (
            cookie.third_party
            and cookie.lifetime_days >= 30
            and is_tracker(cookie.domain, tracker_path)
        ):
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
    if snapshot.cname_hosts and any(
        is_tracker(host, tracker_path) for host in snapshot.cname_hosts
    ):
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
    # By company, not by hostname: the card counts who follows you, not how many
    # subdomains they arrived on, and a block rule for the domain covers them all.
    result.tracker_domains = sorted({tracker_domain(host, tracker_path) for host in trackers})
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
