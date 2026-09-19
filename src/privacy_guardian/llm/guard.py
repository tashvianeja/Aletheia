from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

from privacy_guardian.analysis.pii import detect_pii, redact_text


class OutboundPrivacyError(ValueError):
    pass


def _clean_string(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = "".join(char for char in value if unicodedata.category(char) != "Cf")
    value = re.sub("[‐‑‒–—−]", "-", value)
    # Decode URL-encoded text before scanning, including double encoding.
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    for _ in range(3):
        redacted = redact_text(value, use_ner=True)
        if redacted == value:
            break
        value = redacted
    if any(finding.validator_passed for finding in detect_pii(value, use_ner=False)):
        raise OutboundPrivacyError("A validated identifier survived outbound sanitization")
    return value


def sanitize_outbound(payload: object) -> object:
    def visit(value: object, depth: int) -> object:
        if depth > 25:
            raise OutboundPrivacyError("Outbound structure exceeds maximum depth")
        if isinstance(value, str):
            if len(value) > 2_000_000:
                raise OutboundPrivacyError("Outbound text exceeds maximum size")
            return _clean_string(value)
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if any(finding.validator_passed for finding in detect_pii(str(value))) or (
                isinstance(value, int) and abs(value) >= 100_000_000
            ):
                return "<NUMERIC_IDENTIFIER>"
            return value
        if isinstance(value, (list, tuple)):
            return [visit(item, depth + 1) for item in value]
        if isinstance(value, dict):
            clean: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise OutboundPrivacyError("Outbound object keys must be text")
                new_key = _clean_string(key)
                if new_key in clean:
                    raise OutboundPrivacyError("Sanitized keys collided")
                clean[new_key] = visit(item, depth + 1)
            return clean
        raise OutboundPrivacyError("Unsupported outbound value")

    return visit(payload, 0)
