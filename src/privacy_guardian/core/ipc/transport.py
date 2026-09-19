from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any

from privacy_guardian.core.ipc.protocol import MAX_MESSAGE_BYTES, decode_message, encode_message
from privacy_guardian.util.permissions import secure_path

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def ensure_token(data_dir: Path) -> str:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    secure_path(data_dir)
    path = data_dir / "ipc.token"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        secure_path(path)
        return path.read_text(encoding="ascii").strip()
    token = secrets.token_hex(32)
    secure_path(path)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(token)
    return token


def endpoint(data_dir: Path) -> str:
    if sys.platform == "win32":
        digest = hashlib.sha256(str(data_dir.resolve()).encode()).hexdigest()[:20]
        return rf"\\.\pipe\PrivacyGuardian-{digest}"
    path = data_dir / "control.sock"
    if len(os.fsencode(path)) >= 100:
        import tempfile

        digest = hashlib.sha256(str(data_dir.resolve()).encode()).hexdigest()[:20]
        private = Path(tempfile.gettempdir()) / f"pg-{os.getuid()}-{digest}"
        private.mkdir(mode=0o700, exist_ok=True)
        if private.is_symlink() or private.stat().st_uid != os.getuid():
            raise PermissionError("IPC directory ownership mismatch")
        private.chmod(0o700)
        path = private / "control.sock"
    return str(path)


class ControlServer:
    def __init__(self, data_dir: Path, handler: Handler) -> None:
        self.data_dir = data_dir
        self.handler = handler
        self.token = ensure_token(data_dir)
        self.server: asyncio.AbstractServer | None = None
        self.listener: Any = None
        self._closed = threading.Event()
        self._pipe_thread: threading.Thread | None = None
        self._pipe_slots = threading.BoundedSemaphore(32)
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._closed.clear()
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            self.listener = Listener(endpoint(self.data_dir), family="AF_PIPE", authkey=None)
            self._pipe_thread = threading.Thread(
                target=self._pipe_loop, args=(loop,), daemon=True, name="guardian-pipe"
            )
            self._pipe_thread.start()
        else:
            path = Path(endpoint(self.data_dir))
            # The process lock must be acquired before removing a stale socket.
            path.unlink(missing_ok=True)
            self.server = await asyncio.start_unix_server(self._client, path=path)
            secure_path(path)

    async def _dispatch(self, envelope: dict[str, Any]) -> dict[str, Any]:
        token = envelope.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
            return {
                "v": 1,
                "id": "",
                "ok": False,
                "result": None,
                "error": {"code": "unauthorized", "message": "Authentication failed"},
            }
        request = envelope.get("request")
        if not isinstance(request, dict):
            return {
                "v": 1,
                "id": "",
                "ok": False,
                "result": None,
                "error": {"code": "invalid_request", "message": "Invalid request"},
            }
        try:
            return await self.handler(request)
        except Exception:
            return {
                "v": 1,
                "id": str(request.get("id", ""))[:128],
                "ok": False,
                "result": None,
                "error": {
                    "code": "service_error",
                    "message": "Service could not complete this request",
                },
            }

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if len(self._tasks) >= 32:
            writer.close()
            return
        task = asyncio.current_task()
        if task:
            self._tasks.add(task)
        try:
            while not self._closed.is_set():
                header = await asyncio.wait_for(reader.readexactly(4), 30)
                size = struct.unpack("<I", header)[0]
                if not 0 < size <= MAX_MESSAGE_BYTES:
                    break
                data = await asyncio.wait_for(reader.readexactly(size), 30)
                response = await self._dispatch(decode_message(data))
                writer.write(encode_message(response))
                await writer.drain()
        except (asyncio.IncompleteReadError, TimeoutError, ValueError, ConnectionError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            if task:
                self._tasks.discard(task)

    def _pipe_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        while not self._closed.is_set():
            try:
                connection = self.listener.accept()
            except AuthenticationError:
                continue
            except (OSError, EOFError):
                return
            if not self._pipe_slots.acquire(blocking=False):
                connection.close()
                continue
            threading.Thread(target=self._pipe_client, args=(connection, loop), daemon=True).start()

    def _pipe_client(self, connection: Any, loop: asyncio.AbstractEventLoop) -> None:
        try:
            if not connection.poll(5):
                return
            data = connection.recv_bytes(MAX_MESSAGE_BYTES)
            result = asyncio.run_coroutine_threadsafe(
                self._dispatch(decode_message(data)), loop
            ).result(timeout=30)
            connection.send_bytes(json.dumps(result).encode())
        except (OSError, EOFError, ValueError, TimeoutError):
            pass
        finally:
            connection.close()
            self._pipe_slots.release()

    async def ensure_running(self) -> None:
        healthy = (
            self._pipe_thread is not None and self._pipe_thread.is_alive()
            if sys.platform == "win32"
            else self.server is not None and self.server.is_serving()
        )
        if not healthy and not self._closed.is_set():
            if self.listener:
                self.listener.close()
            await self.start()

    async def stop(self) -> None:
        self._closed.set()
        if self.listener:
            self.listener.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            Path(endpoint(self.data_dir)).unlink(missing_ok=True)
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


async def send_request(
    data_dir: Path, request: dict[str, Any], timeout: float = 25
) -> dict[str, Any]:
    token = ensure_token(data_dir)
    envelope = {"token": token, "request": request}
    if sys.platform == "win32":

        def exchange() -> dict[str, Any]:
            # Authentication is the mandatory JSON-envelope token. Keeping the
            # stdlib challenge disabled avoids an unbounded handshake in accept().
            connection = Client(endpoint(data_dir), family="AF_PIPE", authkey=None)
            try:
                connection.send_bytes(json.dumps(envelope).encode())
                if not connection.poll(timeout):
                    raise TimeoutError("Service response timed out")
                return decode_message(connection.recv_bytes(MAX_MESSAGE_BYTES))
            finally:
                connection.close()

        return await asyncio.wait_for(asyncio.to_thread(exchange), timeout)
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(endpoint(data_dir)), timeout
    )
    try:
        writer.write(encode_message(envelope))
        await writer.drain()
        header = await asyncio.wait_for(reader.readexactly(4), timeout)
        size = struct.unpack("<I", header)[0]
        if not 0 < size <= MAX_MESSAGE_BYTES:
            raise ValueError("Invalid response length")
        return decode_message(await asyncio.wait_for(reader.readexactly(size), timeout))
    finally:
        writer.close()
        await writer.wait_closed()
