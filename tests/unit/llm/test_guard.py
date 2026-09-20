from __future__ import annotations

import pytest

from aletheia.llm.guard import OutboundPrivacyError, sanitize_outbound


@pytest.mark.parametrize(
    "payload",
    [
        "Card 4111111111111111",
        "Card ４１１１１１１１１１１１１１１１",
        "Card 4111\u200b1111\u200b1111\u200b1111",
        "Card 4111‐1111‑1111—1111",
        "card%3D4111111111111111",
        "card%253D4111111111111111",
        "email%3Dmorgan.testperson%40example.test",
        "Transfer to GB82 WEST 1234 5698 7654 32 today please.",
        "SSN 219-09-9999",
    ],
)
def test_sanitize_outbound_removes_encoded_and_unicode_identifiers(payload: str) -> None:
    sanitized = str(sanitize_outbound(payload))
    assert "4111" not in sanitized
    assert "GB82" not in sanitized
    assert "219-09" not in sanitized
    assert "morgan.testperson" not in sanitized
    assert "<" in sanitized


def test_sanitize_outbound_recurses_values_and_keys() -> None:
    payload = {
        "morgan.testperson@example.test": [
            {"card": "4111111111111111", "normal": True},
            4111111111111111,
        ]
    }
    sanitized = sanitize_outbound(payload)
    rendered = repr(sanitized)
    assert "morgan.testperson" not in rendered
    assert "4111111111111111" not in rendered
    assert "<NUMERIC_IDENTIFIER>" in rendered


def test_small_numbers_and_non_sensitive_types_survive() -> None:
    assert sanitize_outbound({"count": 42, "confidence": 0.92, "enabled": True, "empty": None}) == {
        "count": 42,
        "confidence": 0.92,
        "enabled": True,
        "empty": None,
    }


def test_sanitized_key_collision_fails_closed() -> None:
    with pytest.raises(OutboundPrivacyError, match="collided"):
        sanitize_outbound(
            {
                "morgan.testperson@example.test": 1,
                "other.person@example.test": 2,
            }
        )


def test_unsupported_objects_non_text_keys_and_excessive_depth_fail_closed() -> None:
    with pytest.raises(OutboundPrivacyError, match="Unsupported"):
        sanitize_outbound(object())
    with pytest.raises(OutboundPrivacyError, match="keys"):
        sanitize_outbound({1: "value"})
    nested: object = "leaf"
    for _ in range(27):
        nested = [nested]
    with pytest.raises(OutboundPrivacyError, match="depth"):
        sanitize_outbound(nested)


def test_oversized_outbound_text_fails_closed() -> None:
    with pytest.raises(OutboundPrivacyError, match="size"):
        sanitize_outbound("x" * 2_000_001)
