from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

import psutil

from aletheia.config import Settings
from aletheia.core.ipc.protocol import read_message, write_message
from aletheia.core.ipc.transport import send_request


def validate_caller(arguments: list[str], allowed: list[str]) -> bool:
    for argument in arguments:
        if argument.startswith("chrome-extension://"):
            parsed = urlsplit(argument)
            return (
                (parsed.hostname or "") in allowed
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
                and not parsed.username
                and not parsed.port
            )
        if argument in allowed:
            return True
    return False


async def forward(settings: Settings, request: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(7):
        try:
            return await send_request(settings.data_dir, request)
        except (OSError, ConnectionError):
            if attempt == 0:
                command = [sys.executable, "-m", "aletheia"]
                if getattr(sys, "frozen", False):
                    from pathlib import Path

                    app = Path(sys.executable).with_name(
                        "Aletheia.exe" if sys.platform == "win32" else "Aletheia"
                    )
                    command = [str(app)]
                subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            await asyncio.sleep(min(0.1 * 2**attempt, 1))
    return {
        "v": 1,
        "id": request.get("id", ""),
        "ok": False,
        "result": None,
        "error": {"code": "service_unavailable", "message": "Start Aletheia to reconnect"},
    }


def main() -> int:
    if sys.platform == "win32":
        import msvcrt
        import os

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    settings = Settings.load()
    if not validate_caller(sys.argv[1:], settings.allowed_extension_ids):
        return 2
    from uuid import uuid4

    session = str(uuid4())
    host = psutil.Process()
    host_identity = {"_host_pid": host.pid, "_host_created": host.create_time()}

    async def relay() -> None:
        slots = asyncio.Semaphore(6)
        output_lock = asyncio.Lock()
        tasks: set[asyncio.Task[None]] = set()

        async def heartbeat() -> None:
            # This control request never waits for a data-dispatch slot. A long upload
            # cannot make a healthy host appear dead to the service's session lease.
            browser = (
                "chromium"
                if any(arg.startswith("chrome-extension://") for arg in sys.argv)
                else "firefox"
            )
            while True:
                with contextlib.suppress(OSError, TimeoutError, ValueError):
                    await send_request(
                        settings.data_dir,
                        {
                            "v": 1,
                            "id": "host-heartbeat",
                            "type": "ping",
                            "payload": {
                                "_session": session,
                                "browser": browser,
                                "heartbeat_only": True,
                                **host_identity,
                            },
                        },
                        timeout=2,
                    )
                await asyncio.sleep(1)

        heartbeat_task = asyncio.create_task(heartbeat())

        async def dispatch(message: dict[str, Any]) -> None:
            try:
                result = await forward(settings, message)
                async with output_lock:
                    await asyncio.to_thread(write_message, sys.stdout.buffer, result)
            except (OSError, ValueError, TimeoutError):
                pass
            finally:
                slots.release()

        try:
            while True:
                await slots.acquire()
                message = await asyncio.to_thread(read_message, sys.stdin.buffer)
                if message is None:
                    slots.release()
                    break
                payload = message.get("payload")
                if isinstance(payload, dict):
                    message["payload"] = {**payload, "_session": session, **host_identity}
                task = asyncio.create_task(dispatch(message))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            # Tombstone the session before waiting for data work. A result finishing
            # during shutdown must not be published for a browser that has gone away.
            with contextlib.suppress(OSError, TimeoutError, ValueError):
                await send_request(
                    settings.data_dir,
                    {
                        "v": 1,
                        "id": "disconnect",
                        "type": "disconnect",
                        "payload": {"_session": session},
                    },
                    timeout=2,
                )
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=2)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*done, *pending, return_exceptions=True)

    try:
        asyncio.run(relay())
    except (EOFError, ValueError, BrokenPipeError):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
