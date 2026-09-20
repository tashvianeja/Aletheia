from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aletheia.core.events import PrivacyEvent

Handler = Callable[[PrivacyEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    async def publish(self, event: PrivacyEvent) -> None:
        results = await asyncio.gather(
            *(handler(event) for handler in tuple(self._handlers)), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                logging.getLogger(__name__).warning(
                    "event subscriber failed", extra={"error_type": type(result).__name__}
                )
