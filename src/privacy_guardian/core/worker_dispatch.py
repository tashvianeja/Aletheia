from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

UPLOAD_TTL = 120.0
MAX_UPLOADS = 8
MAX_SIZE = 1024 * 1024 * 1024
SAMPLE_SIZE = 5 * 1024 * 1024
FULL_SIZE = 50 * 1024 * 1024


@dataclass
class Upload:
    filename: str
    size: int
    mime: str
    received: int = 0
    sequence: int = 0
    touched: float = field(default_factory=time.monotonic)
    first: bytearray = field(default_factory=bytearray)
    tail: bytearray = field(default_factory=bytearray)


_UPLOADS: dict[str, Upload] = {}


def _expire() -> None:
    for key in list(_UPLOADS):
        if time.monotonic() - _UPLOADS[key].touched > UPLOAD_TTL:
            del _UPLOADS[key]


def start_upload(upload_id: str, filename: str, size: int, mime: str = "") -> None:
    _expire()
    if upload_id in _UPLOADS or len(_UPLOADS) >= MAX_UPLOADS:
        raise ValueError("Upload queue is full or identifier is already in use")
    if not 0 <= size <= MAX_SIZE or not upload_id or len(upload_id) > 128:
        raise ValueError("Invalid upload size or identifier")
    _UPLOADS[upload_id] = Upload(filename=filename[:255], size=size, mime=mime[:128])


def append_upload(upload_id: str, sequence: int, data: bytes) -> None:
    _expire()
    upload = _UPLOADS[upload_id]
    if (
        sequence != upload.sequence
        or len(data) > 675 * 1024
        or upload.received + len(data) > upload.size
    ):
        _UPLOADS.pop(upload_id, None)
        raise ValueError("Invalid upload chunk sequence or length")
    if upload.size <= FULL_SIZE:
        upload.first.extend(data)
    else:
        room = max(0, SAMPLE_SIZE - len(upload.first))
        upload.first.extend(data[:room])
        upload.tail.extend(data)
        if len(upload.tail) > SAMPLE_SIZE:
            del upload.tail[:-SAMPLE_SIZE]
    upload.received += len(data)
    upload.sequence += 1
    upload.touched = time.monotonic()


def finish_upload(upload_id: str) -> Any:
    from privacy_guardian.analysis.worker import analyze_payload

    _expire()
    upload = _UPLOADS.pop(upload_id)
    if upload.received != upload.size:
        raise ValueError("Upload is incomplete")
    partial = upload.size > FULL_SIZE
    return analyze_payload(
        {
            "kind": "document",
            "filename": upload.filename,
            "mime": upload.mime,
            "data": bytes(upload.first + upload.tail),
            "partial": partial,
            "original_size": upload.size,
        }
    )


def abort_upload(upload_id: str) -> None:
    _UPLOADS.pop(upload_id, None)


def refine_context(
    use: str,
    payload: dict[str, object],
    settings: dict[str, object],
    schema_name: str,
    fallback: dict[str, object],
) -> dict[str, object]:
    from typing import cast

    from pydantic import BaseModel

    from privacy_guardian.config import LLMSettings
    from privacy_guardian.llm.client import LLMClient, Use
    from privacy_guardian.llm.schemas import DeepCheckNarrative, PolishedExplanation, RefinedPurpose

    schemas: dict[str, type[BaseModel]] = {
        "purpose": RefinedPurpose,
        "explanation": PolishedExplanation,
        "deep_check": DeepCheckNarrative,
    }
    schema = schemas[schema_name]
    result = LLMClient(LLMSettings.model_validate(settings)).complete(
        cast(Use, use), payload, schema, schema.model_validate(fallback)
    )
    value: dict[str, object] = result.value.model_dump(mode="json")
    return value
