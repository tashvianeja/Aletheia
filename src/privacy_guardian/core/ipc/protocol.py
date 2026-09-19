from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_MESSAGE_BYTES = 900 * 1024
ACTIONS = frozenset(
    {
        "cancel",
        "continue",
        "redact",
        "strip_metadata",
        "review_fields",
        "reject_optional",
        "block",
        "open_settings",
        "mark_expected",
        "view_details",
        "learn_more",
        "clear_clipboard",
    }
)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    id: str = Field(min_length=1, max_length=128)
    type: Literal[
        "ping",
        "event",
        "file_start",
        "file_chunk",
        "file_finish",
        "action",
        "action_poll",
        "context",
        "deep_check",
        "disconnect",
        "focus",
        "fetch_document",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class Error(BaseModel):
    code: str
    message: str


class Response(BaseModel):
    v: Literal[1] = 1
    id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: Error | None = None


def encode_message(message: dict[str, Any]) -> bytes:
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("Message exceeds native messaging limit")
    return struct.pack("<I", len(data)) + data


def decode_message(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("Message exceeds native messaging limit")
    value = json.loads(
        data,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Non-finite JSON number")),
    )
    if not isinstance(value, dict):
        raise ValueError("Message must be an object")
    return value


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = stream.read(size - len(result))
        if not chunk:
            raise EOFError("Truncated native message")
        result.extend(chunk)
    return bytes(result)


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        header += _read_exact(stream, 4 - len(header))
    size = struct.unpack("<I", header)[0]
    if not 0 < size <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid native message length")
    return decode_message(_read_exact(stream, size))


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    stream.write(encode_message(message))
    stream.flush()
