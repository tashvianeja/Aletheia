from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from privacy_guardian.core.ipc.transport import (
    ControlServer,
    endpoint,
    ensure_token,
    send_request,
)


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
