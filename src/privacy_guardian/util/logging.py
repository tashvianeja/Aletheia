from __future__ import annotations

import logging
from collections.abc import MutableMapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from privacy_guardian.util.privacy import sanitize


def redact_processor(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> dict[str, Any]:
    return dict(sanitize(event))


def configure_logging(data_dir: Path, level: str = "INFO") -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(
        log_dir / "guardian.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    (log_dir / "guardian.log").chmod(0o600)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                structlog.stdlib.ExtraAdder(
                    allow=["purpose", "input_tokens", "output_tokens", "latency_ms", "error_type"]
                ),
                redact_processor,
            ],
        )
    )
    logging.basicConfig(
        handlers=[handler], level=getattr(logging, level.upper(), logging.INFO), force=True
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            redact_processor,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
