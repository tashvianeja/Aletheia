from __future__ import annotations

import logging
from pathlib import Path

import structlog

from privacy_guardian.util.logging import configure_logging
from privacy_guardian.util.privacy import redact_text, sanitize

SYNTHETIC_CARD = "4111111111111111"
SYNTHETIC_EMAIL = "morgan.testperson@example.test"
SYNTHETIC_CONTEXT = "Full name: Morgan Testperson; DOB: 1988-02-29; 10 Synthetic Street"


class SensitiveObject:
    def __repr__(self) -> str:
        return f"SensitiveObject(card={SYNTHETIC_CARD}, email={SYNTHETIC_EMAIL})"


def _all_logs(data_dir: Path) -> str:
    logging.shutdown()
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((data_dir / "logs").glob("guardian.log*"))
    )


def test_structlog_and_stdlib_exceptions_never_write_raw_pii(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    structlog.get_logger("synthetic").error(
        "analysis failed",
        nested={"card": SYNTHETIC_CARD, "contact": SYNTHETIC_EMAIL},
        error=ValueError(f"Bad card {SYNTHETIC_CARD} for {SYNTHETIC_EMAIL}"),
        opaque=SensitiveObject(),
    )
    try:
        raise RuntimeError(f"Upload {SYNTHETIC_CARD} belongs to {SYNTHETIC_EMAIL}")
    except RuntimeError:
        logging.getLogger("synthetic.stdlib").exception(
            "worker exception",
            extra={"nested_payload": SensitiveObject()},
        )
    contents = _all_logs(tmp_path)
    assert SYNTHETIC_CARD not in contents
    assert SYNTHETIC_EMAIL not in contents
    assert "<redacted:" in contents


def test_contextual_name_dob_and_postal_address_are_redacted() -> None:
    redacted = redact_text(SYNTHETIC_CONTEXT)
    assert "Morgan Testperson" not in redacted
    assert "1988-02-29" not in redacted
    assert "10 Synthetic Street" not in redacted


def test_sanitize_handles_nested_objects_without_serializing_sensitive_repr() -> None:
    sanitized = sanitize({"level": [{"opaque": SensitiveObject()}]})
    rendered = repr(sanitized)
    assert SYNTHETIC_CARD not in rendered
    assert SYNTHETIC_EMAIL not in rendered
