from __future__ import annotations

import logging

import pytest

from privacy_guardian.core.bus import EventBus
from privacy_guardian.core.events import FormObservedEvent


@pytest.mark.asyncio
async def test_subscriber_failure_isolated_and_other_subscriber_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    received: list[str] = []

    async def broken(_: FormObservedEvent) -> None:
        raise RuntimeError("synthetic subscriber failure")

    async def healthy(event: FormObservedEvent) -> None:
        received.append(event.id)

    bus.subscribe(broken)  # type: ignore[arg-type]
    bus.subscribe(healthy)  # type: ignore[arg-type]
    event = FormObservedEvent()
    with caplog.at_level(logging.WARNING):
        await bus.publish(event)
    assert received == [event.id]
    assert "synthetic subscriber failure" not in caplog.text
    assert "event subscriber failed" in caplog.text


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[str] = []

    async def subscriber(event: FormObservedEvent) -> None:
        received.append(event.id)

    unsubscribe = bus.subscribe(subscriber)  # type: ignore[arg-type]
    unsubscribe()
    await bus.publish(FormObservedEvent())
    assert received == []
