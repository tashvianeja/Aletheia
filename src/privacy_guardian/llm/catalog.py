"""The parts of the cloud settings that do not need the provider SDK to exist.

Importing `google.genai` costs about a third of a second, and Settings has to be able
to draw the model picker whether or not cloud assistance was ever switched on. The list
and the result type live here so that opening a window does not load a network client.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

# What Settings offers before the key has been used to ask which models it can see: the
# Flash family only, because that is the tier whose cost and latency suit a few short
# structured requests per page. Checked against ai.google.dev/gemini-api/docs/models on
# 2026-09-20; a successful connection test replaces it with what the account can really call.
SUGGESTED_MODELS = (
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)
# Flash variants that answer with something other than text, so cannot serve a JSON probe.
_NOT_TEXT = ("image", "tts", "live", "audio", "omni")


def flash_models(names: Iterable[str]) -> list[str]:
    """The text-answering Flash models among these, in the order given."""
    return [
        name
        for name in names
        if "flash" in name and not any(marker in name for marker in _NOT_TEXT)
    ]


class ConnectionCheck(BaseModel):
    """What the Settings "Test" button reports back."""

    ok: bool
    reason: str = ""
    model: str = ""
    latency_ms: int = 0
    models: list[str] = []
