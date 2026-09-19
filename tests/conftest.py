from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest


@pytest.fixture
def unused_tcp_port() -> Iterator[int]:
    """Return a TCP port released immediately before the test uses it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    yield port


@pytest.fixture
def synthetic_card_number() -> str:
    """A published Visa test number; it does not identify a real account."""
    return "4111111111111111"
