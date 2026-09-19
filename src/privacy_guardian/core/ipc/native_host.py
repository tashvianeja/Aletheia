from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

from privacy_guardian.config import Settings
from privacy_guardian.core.ipc.protocol import read_message, write_message
from privacy_guardian.core.ipc.transport import send_request


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
                command = [sys.executable, "-m", "privacy_guardian"]
                if getattr(sys, "frozen", False):
                    from pathlib import Path

                    app = Path(sys.executable).with_name(
                        "PrivacyGuardian.exe" if sys.platform == "win32" else "PrivacyGuardian"
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
        "error": {"code": "service_unavailable", "message": "Start Privacy Guardian to reconnect"},
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

    async def relay() -> None:
        slots = asyncio.Semaphore(8)
        output_lock = asyncio.Lock()
        tasks: set[asyncio.Task[None]] = set()

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
                    message["payload"] = {**payload, "_session": session}
                task = asyncio.create_task(dispatch(message))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=2)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*done, *pending, return_exceptions=True)
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

    try:
        asyncio.run(relay())
    except (EOFError, ValueError, BrokenPipeError):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
