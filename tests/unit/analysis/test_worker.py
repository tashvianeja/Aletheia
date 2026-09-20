from __future__ import annotations

from aletheia.analysis.worker import analyze_payload
from aletheia.core.events import DataCategory


def test_text_payload_scans_identifier_beyond_legacy_two_million_character_limit() -> None:
    late_pii = "Final contact: tailperson@example.test"
    text = ("ordinary " * 250_001) + late_pii
    assert len(text) > 2_000_000

    result = analyze_payload({"kind": "text", "text": text})

    emails = [finding for finding in result.findings if finding.category == DataCategory.EMAIL]
    assert len(emails) == 1
    _start, end = map(int, emails[0].span_ref.split(":"))
    assert end > len(text) - 50
    assert result.partial is False
