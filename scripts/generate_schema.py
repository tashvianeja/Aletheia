from __future__ import annotations

import json
from pathlib import Path

from aletheia.core.events import EVENT_ADAPTER, Decision
from aletheia.core.ipc.protocol import Request, Response

root = Path(__file__).resolve().parents[1] / "extension/schema"
root.mkdir(parents=True, exist_ok=True)
for name, schema in {
    "request": Request.model_json_schema(),
    "response": Response.model_json_schema(),
    "event": EVENT_ADAPTER.json_schema(),
    "decision": Decision.model_json_schema(),
}.items():
    (root / f"{name}.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
