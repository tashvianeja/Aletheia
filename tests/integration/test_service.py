from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from privacy_guardian.config import Settings
from privacy_guardian.core.service import Service
from privacy_guardian.storage import Store

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class InlinePool:
    """Exercise real worker functions while keeping worker payload handles in-process."""

    generation = 0

    async def run(self, function: Any, *args: Any) -> Any:
        return function(*args)

    def close(self) -> None:
        return None


@pytest.fixture
def service(tmp_path: Path) -> Service:
    settings = Settings(data_dir=tmp_path, autostart=False)
    instance = Service(settings, Store(tmp_path / "guardian.sqlite3"))
    instance.pool.close()
    instance.pool = InlinePool()  # type: ignore[assignment]
    yield instance
    instance.store.close()


def request(request_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"v": 1, "id": request_id, "type": kind, "payload": payload}


@pytest.mark.asyncio
async def test_context_analyzes_form_metadata_without_accepting_values(service: Service) -> None:
    metadata = {
        "origin": "https://downloads.example/form?campaign=synthetic",
        "signals": {"title": "Free PDF download", "cta": "Download free guide"},
        "forms": {
            "fields": [
                {
                    "field_id": "phone",
                    "label": "Phone number",
                    "autocomplete": "tel",
                    "filled": True,
                }
            ]
        },
    }
    response = await service.handle_message(request("context-ok", "context", metadata))
    assert response["ok"] is True
    result = response["result"]["forms"]
    assert result["fields"][0]["field"]["category"] == "phone"
    assert result["fields"][0]["badge"] is True
    persisted = repr(service.contexts) + repr(service.store.history())
    assert "synthetic-secret" not in persisted

    with_value = metadata | {
        "forms": {
            "fields": metadata["forms"]["fields"]
            + [{"field_id": "card", "value": "4111111111111111"}]
        }
    }
    rejected = await service.handle_message(request("context-raw", "context", with_value))
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "invalid_request"
    assert "4111111111111111" not in repr(service.contexts)


@pytest.mark.asyncio
async def test_real_document_stream_is_analyzed_and_never_returns_raw_text(
    service: Service,
) -> None:
    document = (FIXTURES / "passport_synthetic.pdf").read_bytes()
    requester = {
        "origin": "https://compress.example/",
        "display_name": "Image Compressor",
    }
    started = await service.handle_message(
        request(
            "start",
            "file_start",
            {
                "upload_id": "synthetic-passport",
                "filename": "passport_synthetic.pdf",
                "size": len(document),
                "mime": "application/pdf",
                "requester": requester,
                "signals": {"title": "Compress images", "cta": "Upload and compress"},
            },
        )
    )
    assert started["ok"] is True
    chunked = await service.handle_message(
        request(
            "chunk",
            "file_chunk",
            {
                "upload_id": "synthetic-passport",
                "sequence": 0,
                "data": base64.b64encode(document).decode("ascii"),
            },
        )
    )
    assert chunked["result"]["received"] == len(document)
    finished = await service.handle_message(
        request("finish", "file_finish", {"upload_id": "synthetic-passport"})
    )
    assert finished["ok"] is True
    assert finished["result"]["decision"]["outcome"] == "INTERVENE"
    categories = {item["category"] for item in finished["result"]["findings"]}
    assert {"government_id.passport", "full_name", "dob", "biometric_photo"} <= categories
    serialized = repr(finished) + repr(service.store.history())
    assert "ERIKSSON" not in serialized
    assert "740812" not in serialized


@pytest.mark.asyncio
async def test_deep_check_uses_cached_real_analyses_and_reports_all_risks(service: Service) -> None:
    service.contexts["https://audit.example"] = {
        "origin": "https://audit.example",
        "analyses": {
            "tracking": {
                "profile": {"fingerprinting": True, "tracker_domains": ["doubleclick.net"]}
            },
            "consent": {"profile": {"dark_patterns": ["hidden_reject"]}},
            "policy": {"profile": {"retention": "after_deletion"}},
        },
    }
    response = await service.handle_message(
        request(
            "deep",
            "deep_check",
            {"origin": "https://audit.example", "cached_only": True},
        )
    )
    assert response["ok"] is True
    assert [item["kind"] for item in response["result"]["findings"]] == [
        "consent",
        "tracking",
        "policy",
    ]
    assert response["result"]["context_available"] is True


@pytest.mark.asyncio
async def test_invalid_or_unknown_messages_have_bounded_non_sensitive_errors(
    service: Service,
) -> None:
    for message in (
        {"v": 2, "id": "bad-version", "type": "ping", "payload": {}},
        request("unknown", "not-a-route", {}),
        request("bad-action", "action", {"event_id": "missing", "action": "continue"}),
    ):
        response = await service.handle_message(message)
        assert response["ok"] is False
        assert response["error"] == {
            "code": "invalid_request",
            "message": "Request failed validation",
        }
