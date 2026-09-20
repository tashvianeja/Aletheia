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
from privacy_guardian.intelligence import embedder
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
@pytest.mark.skipif(
    not embedder.available(),
    reason="on-device sentence encoder not installed; run scripts/fetch_model.py",
)
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
async def test_deep_check_says_a_part_has_started_while_it_is_still_running(
    service: Service,
) -> None:
    """The bug this guards: every part of a run reported only once it was over.

    Waiting for the page to answer is the longest thing a check does, and it used to
    happen behind a checklist of four lines that all still read as "not started". The
    lines then filled in together the moment the reply landed, so the part of the run
    the person actually sat through was the part the card said nothing about.
    """
    import time

    from privacy_guardian.deepcheck import PAGE_STAGES, run_deep_check

    updates: list[tuple[str, str]] = []
    service.progress_listeners.append(
        lambda update: updates.append((update["stage"], update["state"]))
    )
    service.connected_browsers = {"chromium": time.monotonic()}
    service.contexts["https://audit.example"] = {
        "origin": "https://audit.example",
        "analyses": {"tracking": {"profile": {"tracker_domains": ["doubleclick.net"]}}},
    }
    check = asyncio.create_task(run_deep_check(service, {"origin": "https://audit.example"}))

    async def under_way() -> None:
        while ("tracking", "running") not in updates:
            await asyncio.sleep(0.01)

    # The page has not answered yet, and will not until this test lets it.
    await asyncio.wait_for(under_way(), timeout=2)
    assert {stage for stage, state in updates if state == "running"} >= set(PAGE_STAGES)
    assert not [stage for stage, state in updates if state in {"done", "unavailable"}], (
        "nothing may report an answer before the page has given one"
    )

    service.context_updated.set()
    await asyncio.wait_for(check, timeout=10)

    for stage in PAGE_STAGES:
        answers = [index for index, item in enumerate(updates) if item[0] == stage]
        assert len(answers) == 2 and updates[answers[0]][1] == "running"
        assert updates[answers[1]][1] in {"done", "unavailable"}
    assert updates[-1] == ("complete", "done"), "the run is complete last, and only once"


@pytest.mark.asyncio
async def test_deep_check_reports_a_contract_in_words_not_in_its_own_clauses(
    service: Service,
) -> None:
    """The report is the point of the product; the document is the evidence for it.

    Every clause reached the report as its own database key with the sentence it was
    found in underneath — which is the contract, retyped, with a triangle next to it.
    """
    origin = "https://subscription.example"
    terms = (
        "Subscriptions\n"
        "Your subscription renews automatically. To cancel you must notify us at least "
        "14 days before the renewal date.\n"
        "Disputes\n"
        "Any dispute shall be resolved by binding individual arbitration and you waive "
        "any right to a trial by jury.\n"
    )
    await service.handle_message(
        request("terms", "context", {"origin": origin, "terms": {"text": terms}})
    )
    response = await service.handle_message(
        request("deep", "deep_check", {"origin": origin, "cached_only": True})
    )
    summaries = [item["summary"] for item in response["result"]["findings"]]
    assert "This renews and charges you automatically" in summaries
    assert "You give up the right to sue or to join a class action" in summaries
    # The cancellation notice period is not an age requirement, and no summary is a key.
    assert "There is a minimum age for using this" not in summaries
    assert not any("_" in summary for summary in summaries)
    details = " ".join(item["detail"] for item in response["result"]["findings"])
    assert "binding individual arbitration" not in details


@pytest.mark.asyncio
async def test_deep_check_attributes_collection_claims_to_the_policy_that_makes_them(
    service: Service,
) -> None:
    """One sentence for the whole list, and it says who is claiming it.

    A finding per category was the same headline repeated with a different noun under
    it, and it never said the claim came from the policy rather than from this page.
    """
    # The purpose is inferred from the site, not asserted by the caller: what a policy
    # over-collects is only answerable once you know what the service is.
    origin = "https://convert-pdf.example"
    await service.handle_message(
        request(
            "policy",
            "context",
            {
                "origin": origin,
                "policy": {
                    "text": (
                        "We collect your date of birth and your precise location. "
                        "We use your information to provide the service."
                    )
                },
            },
        )
    )
    response = await service.handle_message(
        request("deep", "deep_check", {"origin": origin, "cached_only": True})
    )
    collection = [
        item
        for item in response["result"]["findings"]
        if item["summary"].startswith("The privacy policy claims more")
    ]
    assert len(collection) == 1
    assert collection[0]["detail"] == ("It says it collects date of birth and precise location.")


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


@pytest.mark.asyncio
async def test_tracking_revealed_in_waves_sharpens_one_card(service: Service) -> None:
    """A page shows its hand over several seconds; the person gets one card, not three."""
    origin = "https://news.example"

    async def wave(request_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        response = await service.handle_message(
            request(
                request_id,
                "context",
                {"origin": origin, "tracking": {"snapshot": {"origin": origin, **snapshot}}},
            )
        )
        assert response["ok"] is True, response
        return dict(response["result"]["tracking"]["decision"])

    opening = await wave(
        "wave-one",
        {
            "request_hosts": ["pagead2.googlesyndication.com"],
            "urls": ["https://pagead2.googlesyndication.com/pcs/view?uid=synthetic"],
        },
    )
    sharpened = await wave(
        "wave-two",
        {
            "request_hosts": [
                "pagead2.googlesyndication.com",
                "doubleclick.net",
                "cm.g.doubleclick.net",
            ],
            "urls": [
                "https://pagead2.googlesyndication.com/pcs/view?uid=synthetic",
                "https://cm.g.doubleclick.net/pixel?uid=synthetic",
            ],
            "api_calls": ["canvas.fillText", "canvas.toDataURL"],
        },
    )

    assert sharpened["event_id"] == opening["event_id"]
    assert [event.event_type for event in service.events.values()].count("tracking") == 1
    assert sharpened["outcome"] == "INFORM"
    assert "1 other company" in " ".join(row["label"] for row in opening["findings"])
    later_rows = " ".join(row["label"] for row in sharpened["findings"]).lower()
    # Three hostnames, two companies: cm.g.doubleclick.net is doubleclick.net.
    assert "2 other companies" in later_rows
    assert "clear cookies" in later_rows


@pytest.mark.asyncio
async def test_dismissing_page_panels_reaches_only_a_connected_browser(service: Service) -> None:
    """The desktop's thorough check asks the page to take its cards down; the ask rides
    the next ping, and there is nothing to ask when no browser is listening."""
    service.dismiss_page_panels()
    assert service.browser_commands == []

    first = await service.handle_message(request("hello", "ping", {"browser": "chromium"}))
    assert first["ok"] is True and first["result"]["commands"] == []

    service.dismiss_page_panels()
    second = await service.handle_message(request("again", "ping", {"browser": "chromium"}))
    assert [command["type"] for command in second["result"]["commands"]] == ["dismiss_panels"]

    third = await service.handle_message(request("later", "ping", {"browser": "chromium"}))
    assert third["result"]["commands"] == [], "an ask is delivered once"
