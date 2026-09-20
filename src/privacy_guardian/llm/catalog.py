"""The parts of the cloud settings that do not need the provider SDK to exist.

Importing `google.genai` costs about a third of a second, and Preferences has to be able
to draw the model picker whether or not cloud assistance was ever switched on. The list
and the result type live here so that opening a window does not load a network client.
"""

from __future__ import annotations

from pydantic import BaseModel

# What Preferences offers before the key has been used to ask which models it can see.
# A hard-coded list goes stale, so it is only a starting point: a successful connection
# test replaces it with what the account is really entitled to.
SUGGESTED_MODELS = (
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-pro-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
)


class ConnectionCheck(BaseModel):
    """What the Preferences "Test" button reports back."""

    ok: bool
    reason: str = ""
    model: str = ""
    latency_ms: int = 0
    models: list[str] = []
