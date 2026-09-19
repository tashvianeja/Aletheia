from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import pytest

from privacy_guardian.config import Settings
from privacy_guardian.core.events import (
    DataCategory,
    FileUploadEvent,
    FormField,
    FormObservedEvent,
    Requester,
)
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


class GatePool(InlinePool):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, function: Any, *args: Any) -> Any:
        if function.__name__ == "analyze_payload":
            self.started.set()
            await asyncio.wait_for(self.release.wait(), 2)
        return function(*args)


class FinishGatePool(InlinePool):
    def __init__(self) -> None:
        self.finish_started = asyncio.Event()
        self.release_finish = asyncio.Event()

    async def run(self, function: Any, *args: Any) -> Any:
        if function.__name__ == "finish_upload":
            self.finish_started.set()
            await asyncio.wait_for(self.release_finish.wait(), 2)
        return function(*args)


class PreparationPool(InlinePool):
    def __init__(self) -> None:
        self._pool: object | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def run(self, function: Any, *args: Any) -> Any:
        assert function.__name__ == "prepare_upload_model"
        self.calls += 1
        self.started.set()
        await asyncio.wait_for(self.release.wait(), 2)
        self._pool = object()
        return {"ner_ready": True}


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
async def test_overlapping_context_updates_preserve_each_analysis(service: Service) -> None:
    pool = GatePool()
    service.pool = pool  # type: ignore[assignment]
    origin = "https://concurrent.example"
    policy = request(
        "policy",
        "context",
        {
            "origin": origin,
            "policy": {"text": "We share email addresses with service providers."},
        },
    )
    tracking = request(
        "tracking",
        "context",
        {
            "origin": origin,
            "tracking": {
                "snapshot": {
                    "origin": origin,
                    "request_hosts": ["doubleclick.net"],
                    "urls": ["https://doubleclick.net/pixel?uid=synthetic"],
                }
            },
        },
    )

    policy_task = asyncio.create_task(service.handle_message(policy))
    await asyncio.wait_for(pool.started.wait(), 2)
    tracking_response = await service.handle_message(tracking)
    pool.release.set()
    responses = [await policy_task, tracking_response]

    assert all(response["ok"] for response in responses), responses
    assert service.contexts[origin]["analyses"].keys() >= {"policy", "tracking"}


@pytest.mark.asyncio
async def test_policy_and_terms_cache_are_separated_for_identical_text(service: Service) -> None:
    origin = "https://same-document.example"
    text = "We collect email for service delivery. Disputes use binding arbitration."
    policy = await service.handle_message(
        request("policy", "context", {"origin": origin, "policy": {"text": text}})
    )
    terms = await service.handle_message(
        request("terms", "context", {"origin": origin, "terms": {"text": text}})
    )

    assert "collects" in policy["result"]["policy"]["profile"]
    assert "nothing_unusual" in terms["result"]["terms"]["profile"]
    assert "collects" not in terms["result"]["terms"]["profile"]


@pytest.mark.asyncio
async def test_disconnect_during_file_finish_tombstones_late_analysis(service: Service) -> None:
    pool = FinishGatePool()
    service.pool = pool  # type: ignore[assignment]
    notifications: list[str] = []
    service.decision_listeners.append(lambda decision: notifications.append(decision.event_id))
    session = "browser-session-that-closes"
    content = b"Email: interrupted@example.test"
    requester = {"origin": "https://compress.example", "display_name": "Compressor"}
    started = await service.handle_message(
        request(
            "start-interrupted",
            "file_start",
            {
                "_session": session,
                "upload_id": "interrupted",
                "filename": "interrupted.txt",
                "size": len(content),
                "mime": "text/plain",
                "requester": requester,
            },
        )
    )
    assert started["ok"] is True
    chunked = await service.handle_message(
        request(
            "chunk-interrupted",
            "file_chunk",
            {
                "_session": session,
                "upload_id": "interrupted",
                "sequence": 0,
                "data": base64.b64encode(content).decode(),
            },
        )
    )
    assert chunked["ok"] is True
    finish = asyncio.create_task(
        service.handle_message(
            request(
                "finish-interrupted",
                "file_finish",
                {"_session": session, "upload_id": "interrupted"},
            )
        )
    )
    await asyncio.wait_for(pool.finish_started.wait(), 2)
    disconnected = await service.handle_message(
        request("disconnect-interrupted", "disconnect", {"_session": session})
    )
    pool.release_finish.set()
    finished = await finish

    assert disconnected["ok"] is True
    assert finished["ok"] is True and finished["result"]["aborted"] is True
    assert service.store.history()[0]["status"] == "aborted"
    assert notifications == []


@pytest.mark.asyncio
async def test_form_observation_persists_badges_without_desktop_notification(
    service: Service,
) -> None:
    notifications: list[str] = []
    service.decision_listeners.append(lambda decision: notifications.append(decision.event_id))
    event = FormObservedEvent(
        requester=Requester(
            origin="https://downloads.example/free-guide",
            display_name="Free Guide",
            purpose="free_download",
            purpose_confidence=1,
        ),
        fields=[FormField(field_id="phone", autocomplete="tel")],
    )

    decision = await service.process_event(event)

    assert decision.outcome.value == "INFORM"
    assert service.store.history()[0]["decision"]["event_id"] == event.id
    assert notifications == []


@pytest.mark.asyncio
async def test_upload_analysis_preparation_is_idempotent_for_live_worker(service: Service) -> None:
    pool = PreparationPool()
    service.pool = pool  # type: ignore[assignment]

    service.prepare_upload_analysis()
    service.prepare_upload_analysis()
    await asyncio.wait_for(pool.started.wait(), 2)
    assert pool.calls == 1
    pool.release.set()
    assert service._upload_preparation is not None
    await service._upload_preparation

    service.prepare_upload_analysis()
    await asyncio.sleep(0)
    assert pool.calls == 1


@pytest.mark.asyncio
async def test_partial_upload_never_silently_ignores_unchecked_content(service: Service) -> None:
    partial = FileUploadEvent(
        requester=Requester(origin="https://partial.example", purpose="file_converter"),
        partial=True,
        size_bytes=60 * 1024**2,
    )
    partial_decision = await service.process_event(partial)
    assert partial_decision.outcome.value == "INFORM"
    assert any(
        "partial" in rationale.lower() or "omitted" in rationale.lower()
        for rationale in partial_decision.rationale
    )

    high_impact = FileUploadEvent(
        requester=Requester(origin="https://compress.example", purpose="file_converter"),
        partial=True,
        size_bytes=60 * 1024**2,
        data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT],
    )
    high_impact_decision = await service.process_event(high_impact)
    assert high_impact_decision.outcome.value == "INTERVENE"
    assert any(
        "partial" in rationale.lower() or "omitted" in rationale.lower()
        for rationale in high_impact_decision.rationale
    )


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
