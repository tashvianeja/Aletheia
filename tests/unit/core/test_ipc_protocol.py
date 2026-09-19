from __future__ import annotations

import io
import json
import struct

import pytest
from pydantic import ValidationError

from privacy_guardian.core.ipc.native_host import validate_caller
from privacy_guardian.core.ipc.protocol import (
    MAX_MESSAGE_BYTES,
    Request,
    decode_message,
    encode_message,
    read_message,
    write_message,
)


class ShortRead(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        return super().read(1 if size < 0 else min(size, 1))


def test_native_message_uses_little_endian_length_and_round_trips_unicode() -> None:
    message = {"v": 1, "id": "synthetic", "type": "ping", "payload": {"text": "shield 🛡"}}
    encoded = encode_message(message)
    assert struct.unpack("<I", encoded[:4])[0] == len(encoded) - 4
    assert decode_message(encoded[4:]) == message


def test_reader_handles_fragmented_stream_without_truncation() -> None:
    message = {"v": 1, "id": "fragmented", "type": "ping", "payload": {}}
    assert read_message(ShortRead(encode_message(message))) == message


def test_write_flushes_and_reader_accepts_multiple_frames() -> None:
    stream = io.BytesIO()
    first = {"v": 1, "id": "one", "type": "ping", "payload": {}}
    second = {"v": 1, "id": "two", "type": "focus", "payload": {}}
    write_message(stream, first)
    write_message(stream, second)
    stream.seek(0)
    assert read_message(stream) == first
    assert read_message(stream) == second
    assert read_message(stream) is None


def test_oversized_or_invalid_frames_fail_closed_before_allocation() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        encode_message({"data": "x" * (MAX_MESSAGE_BYTES + 1)})
    with pytest.raises(ValueError, match="length"):
        read_message(io.BytesIO(struct.pack("<I", MAX_MESSAGE_BYTES + 1)))
    with pytest.raises(EOFError, match="Truncated"):
        read_message(io.BytesIO(struct.pack("<I", 50) + b"{}"))


def test_decoder_rejects_non_object_and_nonfinite_json() -> None:
    with pytest.raises(ValueError, match="object"):
        decode_message(json.dumps(["not", "an", "object"]).encode())
    with pytest.raises(ValueError):
        encode_message({"value": float("nan")})


@pytest.mark.parametrize("value", [0, 2, "1", None])
def test_request_rejects_protocol_versions_other_than_integer_one(value: object) -> None:
    with pytest.raises(ValidationError):
        Request.model_validate({"v": value, "id": "req", "type": "ping", "payload": {}})


def test_request_rejects_unknown_type_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Request.model_validate({"v": 1, "id": "req", "type": "execute", "payload": {}})
    with pytest.raises(ValidationError):
        Request.model_validate({"v": 1, "id": "req", "type": "ping", "payload": {}, "raw": "x"})


def test_native_host_caller_validation_requires_exact_extension_id() -> None:
    allowed = ["abcdefghijklmnopabcdefghijklmnop", "privacy-guardian@privacyguardian.local"]
    assert validate_caller(["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"], allowed)
    assert validate_caller(["privacy-guardian@privacyguardian.local"], allowed)
    assert not validate_caller(
        ["chrome-extension://abcdefghijklmnopabcdefghijklmnop.evil/"], allowed
    )
    assert not validate_caller(["https://abcdefghijklmnopabcdefghijklmnop/"], allowed)
    assert not validate_caller([], allowed)
