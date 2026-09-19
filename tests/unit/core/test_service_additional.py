from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
import pytest

from privacy_guardian.config import Settings
from privacy_guardian.core.events import (
    ClipboardReadEvent,
    ConsentBannerEvent,
    DataCategory,
    Decision,
    FileUploadEvent,
    Outcome,
    PermissionRequestEvent,
    Requester,
    TrackingEvent,
    UserResponse,
)
from privacy_guardian.core.service import Service
from privacy_guardian.storage import Store


class FakePool:
    generation = 1

    def __init__(self) -> None:
        self._pool: object | None = None
        self.active = 0
        self.last_used = 0.0
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.recycled = 0

    async def run(self, function: Any, *args: Any) -> Any:
        self.calls.append((function.__name__, args))
        return True

    def recycle(self) -> None:
        self.recycled += 1
        self._pool = None

    def close(self) -> None:
        self.recycle()


@pytest.fixture
def service(tmp_path: Path) -> Service:
    instance = Service(
        Settings(data_dir=tmp_path, autostart=False), Store(tmp_path / "guardian.sqlite3")
    )
    instance.pool.close()
    instance.pool = FakePool()  # type: ignore[assignment]
    yield instance
    instance.metadata_executor.shutdown(wait=False, cancel_futures=True)
    instance.pool.close()
    instance.store.close()


@pytest.mark.asyncio
async def test_cloud_scheduler_deduplicates_and_releases_key(service: Service) -> None:
    called: list[str] = []

    async def factory() -> None:
        called.append("started")
        await asyncio.sleep(0)

    service._schedule_cloud("disabled", factory)
    assert service.background_tasks == set()
    service.settings.llm.enabled = True
    service._schedule_cloud("same-key", factory)
    service._schedule_cloud("same-key", factory)
    await asyncio.gather(*service.background_tasks)

    assert called == ["started"]
    assert "same-key" not in service.cloud_keys


def test_cloud_executor_is_lazy_and_owned_workers_are_terminated(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions: list[str] = []

    class Process:
        def is_alive(self) -> bool:
            return True

        def terminate(self) -> None:
            actions.append("terminated")

    class Executor:
        def __init__(self, **_kwargs: object) -> None:
            self._processes = {1: Process()}

        def shutdown(self, **_kwargs: object) -> None:
            actions.append("shutdown")

    monkeypatch.setattr("privacy_guardian.core.service.ProcessPoolExecutor", Executor)
    first = service.llm_executor
    assert service.llm_executor is first
    service._close_cloud()

    assert actions == ["terminated", "shutdown"]
    assert service._llm_executor is None


@pytest.mark.asyncio
async def test_maintenance_expires_all_bounded_runtime_state(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = service.pool
    assert isinstance(pool, FakePool)
    pool._pool = object()
    stale_event = PermissionRequestEvent(
        id="stale-event",
        ts=datetime.now(UTC) - timedelta(minutes=20),
        requester=Requester(origin="https://stale.example"),
        data_categories=[DataCategory.CAMERA],
    )
    stale_decision = Decision(
        event_id=stale_event.id,
        outcome=Outcome.INTERVENE,
        risk=0.8,
        explanation="Synthetic",
        actions=["open_settings"],
        default_action="open_settings",
    )
    service.events[stale_event.id] = stale_event
    service.decisions[stale_event.id] = stale_decision
    service.pending_since[stale_event.id] = 0
    service.event_owners[stale_event.id] = "old-session"
    service.response_locks[stale_event.id] = asyncio.Lock()
    service.actions[stale_event.id] = {"action": "open_settings"}
    service.uploads["stale-upload"] = {
        "touched": 0,
        "requester": Requester(origin="https://upload.example"),
    }
    service.closed_sessions["closed"] = 0
    service.connected_browsers["chrome"] = 0
    service.browser_sessions["browser-session"] = "chrome"
    service.contexts["https://unused.example"] = {"updated_at": 0}
    ensured: list[bool] = []

    async def ensure_running() -> None:
        ensured.append(True)

    service.control.ensure_running = ensure_running  # type: ignore[method-assign]
    sleeps = 0

    async def sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("privacy_guardian.core.service.asyncio.sleep", sleep)
    monkeypatch.setattr("privacy_guardian.core.service.time.monotonic", lambda: 1_000.0)

    with pytest.raises(asyncio.CancelledError):
        await service._maintenance()

    assert ensured == [True, True]
    assert pool.recycled == 1
    assert pool.calls == [("abort_upload", ("stale-upload",))]
    assert service.events == {}
    assert service.uploads == {}
    assert service.closed_sessions == {}
    assert service.connected_browsers == {}
    assert service.browser_sessions == {}
    assert service.contexts == {}


def test_preferences_apply_public_origin_overrides(service: Service) -> None:
    service.preferences.requester_overrides["https://example.test"] = "allow"
    service.preferences.expected_permissions["https://example.test"] = [DataCategory.CAMERA]
    requester = Requester(origin="https://example.test/private?synthetic=1")

    preferences = service.preferences_for(requester)

    assert preferences.requester_overrides[requester.key] == "allow"
    assert preferences.expected_permissions[requester.key] == [DataCategory.CAMERA]


def test_native_host_process_identity_detects_exit_and_pid_reuse(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Process:
        def __init__(self, pid: int) -> None:
            if pid == 303:
                raise psutil.NoSuchProcess(pid)
            self.pid = pid

        def is_running(self) -> bool:
            return True

        def status(self) -> str:
            return psutil.STATUS_RUNNING

        def create_time(self) -> float:
            return {101: 10.0, 202: 99.0}[self.pid]

    monkeypatch.setattr("privacy_guardian.core.service.psutil.Process", Process)
    service.session_processes.update(
        {
            "live": (101, 10.0),
            "reused": (202, 20.0),
            "exited": (303, 30.0),
        }
    )

    assert service._session_process_alive("live") is True
    assert service._session_process_alive("reused") is False
    assert service._session_process_alive("exited") is False
    assert service._session_process_alive("direct-local-client") is True


@pytest.mark.asyncio
async def test_response_persists_mark_expected_remember_and_is_idempotent(
    service: Service,
) -> None:
    event = PermissionRequestEvent(
        requester=Requester(kind="application", bundle_id="test.synthetic.app"),
        data_categories=[DataCategory.CAMERA],
    )
    decision = Decision(
        event_id=event.id,
        outcome=Outcome.INTERVENE,
        risk=0.8,
        explanation="Synthetic permission",
        actions=["mark_expected", "open_settings"],
        default_action="open_settings",
    )
    service.events[event.id] = event
    service.decisions[event.id] = decision
    service.pending_since[event.id] = 0
    service.store.save_event(event)
    service.store.save_decision(decision)
    notified: list[tuple[str, str]] = []
    service.action_listeners.append(lambda event_id, action: notified.append((event_id, action)))
    response = UserResponse(event_id=event.id, action="mark_expected", remember=True)

    result = await service.respond(response)
    repeated = await service.respond(response)

    assert repeated == result == {"action": "mark_expected", "event_id": event.id}
    assert service.preferences.expected_permissions[event.requester.key] == [DataCategory.CAMERA]
    assert service.preferences.requester_overrides[event.requester.key] == "ask"
    assert notified == [(event.id, "mark_expected")]
    assert event.id not in service.pending_since


@pytest.mark.asyncio
async def test_response_rejects_unknown_unavailable_and_missing_redaction(
    service: Service,
) -> None:
    with pytest.raises(ValueError, match="Unknown decision"):
        await service.respond(UserResponse(event_id="missing", action="cancel"))

    event = FileUploadEvent(requester=Requester(origin="https://files.example"))
    decision = Decision(
        event_id=event.id,
        outcome=Outcome.INTERVENE,
        risk=0.7,
        explanation="Synthetic upload",
        actions=["redact", "cancel"],
        default_action="cancel",
    )
    service.events[event.id] = event
    service.decisions[event.id] = decision
    with pytest.raises(ValueError, match="Action is not available"):
        await service.respond(UserResponse(event_id=event.id, action="continue"))
    with pytest.raises(ValueError, match="no longer available"):
        await service.respond(UserResponse(event_id=event.id, action="redact"))


@pytest.mark.asyncio
async def test_continue_releases_worker_payload_and_notifies_listener(service: Service) -> None:
    event = FileUploadEvent(
        requester=Requester(origin="https://files.example"),
        payload_ref="synthetic-handle",
        data_categories=[DataCategory.EMAIL],
    )
    decision = Decision(
        event_id=event.id,
        outcome=Outcome.INTERVENE,
        risk=0.7,
        explanation="Synthetic upload",
        actions=["continue", "cancel"],
        default_action="cancel",
    )
    service.events[event.id] = event
    service.decisions[event.id] = decision
    service.store.save_event(event)
    service.store.save_decision(decision)

    result = await service.respond(UserResponse(event_id=event.id, action="continue"))

    pool = service.pool
    assert isinstance(pool, FakePool)
    assert pool.calls == [("release_payload", ("synthetic-handle",))]
    assert event.payload_ref is None
    assert result["action"] == "continue"


@pytest.mark.asyncio
async def test_disconnect_validates_owner_and_cleans_session_state(service: Service) -> None:
    def request(identifier: str, payload: dict[str, object]) -> dict[str, object]:
        return {"v": 1, "id": identifier, "type": "disconnect", "payload": payload}

    missing = await service.handle_message(request("missing", {}))
    assert missing["ok"] is False

    event = PermissionRequestEvent(requester=Requester(origin="https://site.example"))
    decision = Decision(
        event_id=event.id,
        outcome=Outcome.INTERVENE,
        risk=0.7,
        explanation="Synthetic",
        actions=["open_settings"],
        default_action="open_settings",
    )
    service.events[event.id] = event
    service.decisions[event.id] = decision
    service.pending_since[event.id] = 0
    service.event_owners[event.id] = "owner"
    service.store.save_event(event)
    service.store.save_decision(decision)
    wrong_owner = await service.handle_message(
        request("wrong", {"_session": "other", "event_id": event.id})
    )
    assert wrong_owner["ok"] is False
    disconnected = await service.handle_message(
        request("right", {"_session": "owner", "event_id": event.id})
    )
    assert disconnected["result"] == {"disconnected": True, "event_id": event.id}

    service.uploads["upload"] = {
        "session": "whole",
        "touched": 0,
        "event_id": "synthetic-upload-event",
    }
    service.contexts["https://site.example"] = {"session": "whole"}
    service.browser_sessions["whole"] = "chrome"
    service.session_processes["whole"] = (123, 1.0)
    service.connected_browsers["chrome"] = 1
    complete = await service.handle_message(request("whole", {"_session": "whole"}))
    assert complete["result"] == {"disconnected": True}
    assert service.uploads == {}
    assert service.contexts == {}
    assert service.browser_sessions == {}
    assert service.session_processes == {}
    assert service.connected_browsers == {}


@pytest.mark.asyncio
async def test_a_desktop_notice_is_never_answered_on_the_person_s_behalf(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is held up by a desktop notice, and its default opens system settings.

    Taking that default for someone who stepped away would open System Settings by
    itself, minutes later, with nobody there. It waits instead.
    """
    desktop = PermissionRequestEvent(
        id="desktop-event",
        source="os",
        requester=Requester(kind="application", bundle_id="com.synthetic.grabber"),
        data_categories=[DataCategory.CAMERA],
        permission="camera",
    )
    page = FileUploadEvent(
        id="page-event",
        source="browser",
        requester=Requester(origin="https://shrinkpix.example"),
        data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT],
    )
    for event, actions, default in (
        (desktop, ["open_settings", "continue"], "open_settings"),
        (page, ["cancel", "continue"], "cancel"),
    ):
        decision = Decision(
            event_id=event.id,
            outcome=Outcome.INTERVENE,
            risk=0.8,
            explanation="Synthetic",
            actions=actions,
            default_action=default,
        )
        service.events[event.id] = event
        service.decisions[event.id] = decision
        service.store.save_event(event)
        service.store.save_decision(decision)
        service.pending_since[event.id] = 0
    service.browser_sessions["browser-session"] = "chrome"
    service.control.ensure_running = _noop  # type: ignore[method-assign]
    sleeps = 0

    async def sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr("privacy_guardian.core.service.asyncio.sleep", sleep)
    monkeypatch.setattr("privacy_guardian.core.service.time.monotonic", lambda: 1_000.0)

    with pytest.raises(asyncio.CancelledError):
        await service._maintenance()

    assert "desktop-event" not in service.actions
    assert service.actions["page-event"] == {"action": "cancel", "event_id": "page-event"}


async def _noop() -> None:
    return None


def _tracking(signals: list[str], domains: list[str], confidence: float = 0.6) -> TrackingEvent:
    return TrackingEvent(
        requester=Requester(origin="https://news.test", display_name="news.test"),
        data_categories=[DataCategory.DEVICE_IDENTIFIERS],
        tracker_domains=domains,
        signals=signals,
        confidence=confidence,
    )


@pytest.mark.asyncio
async def test_repeat_of_the_same_warning_updates_one_notice(service: Service) -> None:
    first = await service.process_event(_tracking(["known_tracker_requests"], ["a.test"]))
    later = await service.process_event(
        _tracking(["known_tracker_requests"], ["a.test", "b.test", "c.test"], confidence=0.9)
    )

    assert later.event_id == first.event_id
    assert len(service.decisions) == 1


@pytest.mark.asyncio
async def test_a_new_tracking_mechanism_raises_its_own_notice(service: Service) -> None:
    first = await service.process_event(_tracking(["known_tracker_requests"], ["a.test"]))
    fingerprinting = await service.process_event(
        _tracking(["known_tracker_requests", "fingerprinting"], ["a.test"])
    )

    assert fingerprinting.event_id != first.event_id
    assert fingerprinting.outcome != Outcome.IGNORE


@pytest.mark.asyncio
async def test_an_answered_warning_is_not_raised_again(service: Service) -> None:
    first = await service.process_event(_tracking(["known_tracker_requests"], ["a.test"]))
    await service.respond(UserResponse(event_id=first.event_id, action="learn_more"))

    again = await service.process_event(_tracking(["known_tracker_requests"], ["a.test"]))

    assert again.event_id == first.event_id
    assert again.outcome == Outcome.IGNORE
    assert again.event_id not in service.pending_since


@pytest.mark.asyncio
async def test_a_repeat_never_withdraws_a_question_already_on_screen(service: Service) -> None:
    banner = ConsentBannerEvent(
        requester=Requester(origin="https://news.test", display_name="news.test"),
        purposes=["necessary", "advertising"],
        dark_patterns=["layered_rejection"],
        cmp="onetrust",
    )
    asked = await service.process_event(banner)
    assert asked.outcome == Outcome.INTERVENE

    # The banner re-renders and is reported again while the person is still deciding.
    repeated = await service.process_event(banner.model_copy(update={"id": "second"}))

    assert repeated.outcome == Outcome.INTERVENE
    assert repeated.actions == asked.actions


@pytest.mark.asyncio
async def test_two_uploads_of_one_file_are_each_asked_about(service: Service) -> None:
    """An answer to one upload must never be reused as the answer to the next."""
    upload = FileUploadEvent(
        requester=Requester(origin="https://shrink.test", display_name="shrink.test"),
        filename="passport.pdf",
        size_bytes=2048,
        data_categories=[DataCategory.GOVERNMENT_ID_PASSPORT],
    )
    first = await service.process_event(upload)
    second = await service.process_event(upload.model_copy(update={"id": "second-upload"}))

    assert second.event_id != first.event_id


@pytest.mark.asyncio
async def test_a_second_clipboard_read_is_a_second_exposure(service: Service) -> None:
    """A read happened at a moment; it is not a standing property of the app."""
    read = ClipboardReadEvent(
        requester=Requester(kind="application", bundle_id="com.synthetic.notes"),
        writer_key="com.synthetic.editor",
        data_categories=[DataCategory.FINANCIAL_CARD_NUMBER],
    )
    first = await service.process_event(read)
    again = await service.process_event(read.model_copy(update={"id": "second-read"}))

    assert again.event_id != first.event_id
