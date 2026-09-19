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


def sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(k): (
                v
                if k
                in {
                    "id",
                    "event_id",
                    "correlation_id",
                    "ts",
                    "stable_hash",
                    "document_hash",
                    "digest",
                }
                else sanitize(v)
            )
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
    return value
