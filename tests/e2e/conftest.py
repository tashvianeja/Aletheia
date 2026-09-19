from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from aiohttp import web

from tests.e2e.fixture_server import FixtureState, create_fixture_app


@pytest_asyncio.fixture
async def fixture_site(unused_tcp_port: int) -> AsyncIterator[tuple[str, FixtureState]]:
    state = FixtureState()
    runner = web.AppRunner(create_fixture_app(state))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    try:
        yield f"http://127.0.0.1:{unused_tcp_port}", state
    finally:
        await runner.cleanup()
