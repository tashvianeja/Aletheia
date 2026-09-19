from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

import pytest

from privacy_guardian.core.ipc.protocol import MAX_MESSAGE_BYTES, decode_message, encode_message
from privacy_guardian.core.ipc.transport import (
    ControlServer,
    endpoint,
    ensure_token,
    send_request,
)


class MemoryWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def test_ipc_token_is_stable_random_and_private(tmp_path: Path) -> None:
    first = ensure_token(tmp_path)
    second = ensure_token(tmp_path)
    assert first == second
    assert len(first) == 64
    assert int(first, 16) >= 0
    if os.name != "nt":
        assert (tmp_path / "ipc.token").stat().st_mode & 0o777 == 0o600
        assert tmp_path.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_dispatch_rejects_wrong_token_without_calling_handler(tmp_path: Path) -> None:
    received: list[dict[str, object]] = []

    async def handler(request: dict[str, object]) -> dict[str, object]:
        received.append(request)
        return {"v": 1, "id": str(request["id"]), "ok": True, "result": {}, "error": None}

    server = ControlServer(tmp_path, handler)  # type: ignore[arg-type]
    response = await server._dispatch(
        {
            "token": "0" * 64,
            "request": {"v": 1, "id": "unauthorized", "type": "ping", "payload": {}},
        }
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "unauthorized"  # type: ignore[index]
    assert received == []


@pytest.mark.asyncio
async def test_stream_client_dispatches_authenticated_frame_portably(tmp_path: Path) -> None:
    received: list[str] = []

    async def handler(request: dict[str, object]) -> dict[str, object]:
        received.append(str(request["id"]))
        return {
            "v": 1,
            "id": str(request["id"]),
            "ok": True,
            "result": {"pong": True},
            "error": None,
        }

    server = ControlServer(tmp_path, handler)  # type: ignore[arg-type]
    reader = asyncio.StreamReader()
    reader.feed_data(
        encode_message(
            {
                "token": server.token,
                "request": {"v": 1, "id": "portable-frame", "type": "ping", "payload": {}},
            }
        )
    )
    reader.feed_eof()
    writer = MemoryWriter()

    await server._client(reader, writer)  # type: ignore[arg-type]

    size = struct.unpack("<I", writer.data[:4])[0]
    response = decode_message(bytes(writer.data[4 : 4 + size]))
    assert response["ok"] is True
    assert response["result"] == {"pong": True}
    assert received == ["portable-frame"]
    assert writer.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_frame",
    [struct.pack("<I", MAX_MESSAGE_BYTES + 1), b"\x01\x00"],
    ids=["oversized", "truncated-header"],
)
async def test_stream_client_rejects_invalid_or_incomplete_frames_portably(
    tmp_path: Path, invalid_frame: bytes
) -> None:
    called = False

    async def handler(_request: dict[str, object]) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    server = ControlServer(tmp_path, handler)  # type: ignore[arg-type]
    reader = asyncio.StreamReader()
    reader.feed_data(invalid_frame)
    reader.feed_eof()
    writer = MemoryWriter()

    await server._client(reader, writer)  # type: ignore[arg-type]

    assert called is False
    assert writer.data == b""
    assert writer.closed is True


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name == "nt", reason="Unix socket behavior; Windows AF_PIPE runs in Windows CI"
)
async def test_authenticated_request_round_trips_over_real_unix_socket() -> None:
    async def handler(request: dict[str, object]) -> dict[str, object]:
        return {
            "v": 1,
            "id": str(request["id"]),
            "ok": True,
            "result": {"pong": True},
            "error": None,
        }

    with tempfile.TemporaryDirectory(prefix="pg-ipc-", dir="/tmp") as short_dir:
        data_dir = Path(short_dir)
        server = ControlServer(data_dir, handler)  # type: ignore[arg-type]
        await server.start()
        try:
            socket_path = Path(endpoint(data_dir))
            assert socket_path.stat().st_mode & 0o777 == 0o600
            response = await send_request(
                data_dir, {"v": 1, "id": "roundtrip", "type": "ping", "payload": {}}
            )
            assert response == {
                "v": 1,
                "id": "roundtrip",
                "ok": True,
                "result": {"pong": True},
                "error": None,
            }
        finally:
            await server.stop()
        assert not Path(endpoint(data_dir)).exists()


@pytest.mark.asyncio
@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="requires the native Windows AF_PIPE")
async def test_windows_pipe_rejects_wrong_envelope_and_expires_idle_client(
    tmp_path: Path,
) -> None:
    from multiprocessing.connection import Client

    received: list[str] = []

    async def handler(request: dict[str, object]) -> dict[str, object]:
        received.append(str(request["id"]))
        return {
            "v": 1,
            "id": str(request["id"]),
            "ok": True,
            "result": {"pong": True},
            "error": None,
        }

    server = ControlServer(tmp_path, handler)  # type: ignore[arg-type]
    await server.start()
    idle = await asyncio.to_thread(Client, endpoint(tmp_path), family="AF_PIPE", authkey=None)
    wrong = await asyncio.to_thread(Client, endpoint(tmp_path), family="AF_PIPE", authkey=None)
    try:
        envelope = {
            "token": "0" * 64,
            "request": {"v": 1, "id": "wrong-token", "type": "ping", "payload": {}},
        }
        await asyncio.to_thread(wrong.send_bytes, json.dumps(envelope).encode())
        assert await asyncio.to_thread(wrong.poll, 2)
        response = json.loads(
            (await asyncio.to_thread(wrong.recv_bytes, MAX_MESSAGE_BYTES)).decode()
        )
        assert response["ok"] is False
        assert response["error"]["code"] == "unauthorized"
        assert received == []

        healthy = await send_request(
            tmp_path,
            {"v": 1, "id": "parallel-healthy", "type": "ping", "payload": {}},
            timeout=2,
        )
        assert healthy["ok"] is True
        assert received == ["parallel-healthy"]

        await asyncio.sleep(5.2)
        with pytest.raises((EOFError, OSError)):
            await asyncio.wait_for(asyncio.to_thread(idle.recv_bytes, MAX_MESSAGE_BYTES), timeout=1)
    finally:
        idle.close()
        wrong.close()
        await server.stop()
