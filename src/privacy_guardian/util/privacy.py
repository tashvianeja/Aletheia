from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_PATTERNS = (
    (
        "credentials",
        re.compile(
            r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})\b"
        ),
    ),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    (
        "identifier",
        re.compile(
            r"(?<!\w)(?:\d[ -]?){7,19}(?!\w)|\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b|\b[A-Z]\d{7,9}\b"
        ),
    ),
)


def redact_text(value: str) -> str:
    value = re.sub(
        r"(?i)(?:full[ _-]?name|patient[ _-]?name|name)\s*[:=]\s*[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3}",
        "<redacted:full_name>",
        value,
    )
    value = re.sub(
        r"(?i)\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){1,4}(?:street|st|avenue|ave|road|rd|lane|drive|boulevard|way)\b",
        "<redacted:postal_address>",
        value,
    )
    for category, pattern in _PATTERNS:
        value = pattern.sub(f"<redacted:{category}>", value)
    return value


def safe_origin(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme in {"http", "https"} and parts.hostname:
            port = f":{parts.port}" if parts.port else ""
            return urlunsplit((parts.scheme, parts.hostname + port, "", "", ""))
    except ValueError:
        pass
    return redact_text(value)[:256]


def _safe_identifier(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if key in {"id", "event_id", "correlation_id"}:
        return bool(
            re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value, re.I
            )
        )
    if key in {"stable_hash", "document_hash", "digest"}:
        return bool(re.fullmatch(r"[0-9a-f]{64}", value, re.I))
    if key == "ts":
        from datetime import datetime

        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False
    return False


def sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(k): (v if _safe_identifier(str(k), v) else sanitize(v))
            for k, v in value.items()
            if k
            not in {
                "text",
                "content",
                "data",
                "value",
                "password",
                "api_key",
                "payload_ref",
                "span_ref",
            }
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"
