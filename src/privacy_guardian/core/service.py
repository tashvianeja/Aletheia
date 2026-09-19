from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from privacy_guardian.config import Settings
from privacy_guardian.core.bus import EventBus
from privacy_guardian.core.events import (
    DataCategory,
    Decision,
    FileUploadEvent,
    Finding,
    Outcome,
    PrivacyEvent,
    Requester,
    UserResponse,
)
from privacy_guardian.core.ipc.protocol import ACTIONS, Request
from privacy_guardian.core.ipc.transport import ControlServer
from privacy_guardian.core.pool import AnalysisPool
from privacy_guardian.core.worker_dispatch import (
    abort_upload,
    append_upload,
    finish_upload,
    start_upload,
)
from privacy_guardian.engine.context import Observation, SiteOrAppProfile
from privacy_guardian.engine.decision import decide
from privacy_guardian.engine.preferences import LearnedRules, UserPreferences
from privacy_guardian.storage import Store
from privacy_guardian.util.privacy import safe_origin, sanitize


class Service:
    def __init__(self, settings: Settings, store: Store | None = None) -> None:
        self.settings = settings
        self.store = store or Store(settings.data_dir / "guardian.sqlite3")
        self.bus = EventBus()
        self.pool = AnalysisPool(settings.analysis_timeout_seconds)
        self.control = ControlServer(settings.data_dir, self.handle_message)
        self.preferences = UserPreferences.model_validate(
            self.store.get_preferences().get("user", {})
        )
        self.learned_rules = LearnedRules.model_validate(
            self.store.get_learned_rules().get("user", {})
        )
        self.decision_listeners: list[Callable[[Decision], None]] = []
        self.focus_listeners: list[Callable[[], None]] = []
        self.progress_listeners: list[Callable[[str], None]] = []
        self.events: dict[str, PrivacyEvent] = {}
        self.decisions: dict[str, Decision] = {}
        self.actions: dict[str, dict[str, Any]] = {}
        self.pending_since: dict[str, float] = {}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.contexts: dict[str, dict[str, Any]] = {}
        self.browser_commands: list[dict[str, Any]] = []
        self.context_updated = asyncio.Event()
        self.pending_context_id: str | None = None
        self.focused_origin = ""
        self.connected_browsers: dict[str, float] = {}
        self.paused_until: datetime | None = None
        self.adapter: Any = None
        self.llm_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="guardian-cloud")
        self.background_tasks: set[asyncio.Task[None]] = set()
        self._sweeper: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.control.start()
        self.bus.subscribe(self._on_event)
        self.store.purge(self.settings.retention_days)
        self._sweeper = asyncio.create_task(self._maintenance())
        from privacy_guardian.analysis.worker import warm_analysis

        async def warm() -> None:
            with contextlib.suppress(RuntimeError):
                await self.pool.run(warm_analysis)

        asyncio.create_task(warm())

    async def stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
        if self.adapter:
            await asyncio.to_thread(self.adapter.stop)
        await self.control.stop()
        for task in tuple(self.background_tasks):
            task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        self.llm_executor.shutdown(wait=False, cancel_futures=True)
        self.pool.close()
        self.store.close()

    async def _on_event(self, event: PrivacyEvent) -> None:
        await self.process_event(event)

    async def _maintenance(self) -> None:
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            if (
                self.pool._pool is not None
                and not self.pool.active
                and not self.uploads
                and now - self.pool.last_used > 120
            ):
                self.pool.recycle()
            for event_id, since in list(self.pending_since.items()):
                if (
                    now - since >= self.settings.popup_timeout_seconds
                    and event_id not in self.actions
                ):
                    decision = self.decisions[event_id]
                    await self.respond(
                        UserResponse(event_id=event_id, action=decision.default_action)
                    )
            for upload_id, meta in list(self.uploads.items()):
                if now - meta["touched"] > 120:
                    await self.pool.run(abort_upload, upload_id)
                    self.uploads.pop(upload_id, None)
            for event_id, event in list(self.events.items()):
                if (datetime.now(UTC) - event.ts).total_seconds() > 600:
                    self.events.pop(event_id, None)
                    self.decisions.pop(event_id, None)
                    self.actions.pop(event_id, None)
                    self.pending_since.pop(event_id, None)

    def _profile(self, requester: Requester) -> SiteOrAppProfile:
        kind = "site" if requester.kind == "website" else "app"
        return SiteOrAppProfile.model_validate(self.store.get_profile(kind, requester.key) or {})

    async def process_event(
        self, event: PrivacyEvent, findings: list[Finding] | None = None
    ) -> Decision:
        from privacy_guardian.analysis.forms import label_field
        from privacy_guardian.analysis.purpose import enrich_requester
        from privacy_guardian.core.events import FormObservedEvent, FormSubmitEvent

        event.requester = enrich_requester(event.requester)
        if isinstance(event, FormObservedEvent):
            event.fields = [label_field(field) for field in event.fields]
            event.data_categories = sorted(
                {
                    field.category
                    for field in event.fields
                    if field.category is not None
                    and (not isinstance(event, FormSubmitEvent) or field.filled)
                },
                key=str,
            )
        event.requester.origin = safe_origin(event.requester.origin)
        if findings:
            event.data_categories = sorted(
                set(event.data_categories) | {f.category for f in findings}, key=str
            )
        profile = self._profile(event.requester)
        decision = decide(event, findings, profile, self.preferences, self.learned_rules)
        if self.paused_until and datetime.now(UTC) < self.paused_until:
            decision = decision.model_copy(
                update={
                    "outcome": Outcome.IGNORE,
                    "explanation": "Monitoring is paused.",
                    "actions": ["continue"],
                    "default_action": "continue",
                }
            )
        self.events[event.id] = event
        self.decisions[event.id] = decision
        self.store.save_event(event)
        self.store.save_decision(decision)
        profile.recent_observations = [
            o for o in profile.recent_observations if event.ts - o.ts < timedelta(hours=24)
        ]
        from privacy_guardian.engine.necessity import Necessity, necessity_for

        observation = Observation(
            categories=event.data_categories,
            ts=event.ts,
            confidence=getattr(event, "confidence", 0),
            red_flags=[
                category
                for category in event.data_categories
                if necessity_for(
                    event.requester.purpose, category, event.requester.purpose_confidence
                ).verdict
                == Necessity.RED_FLAG
            ],
        )
        if event.event_type != "form_observed":
            profile.recent_observations.append(observation)
        self.store.put_profile(
            "site" if event.requester.kind == "website" else "app",
            event.requester.key,
            profile.model_dump(mode="json"),
        )
        if decision.outcome == Outcome.INTERVENE:
            self.pending_since[event.id] = time.monotonic()
        if decision.outcome != Outcome.IGNORE:
            for callback in tuple(self.decision_listeners):
                try:
                    callback(decision)
                except Exception:
                    # User interface failures cannot escape the service boundary.
                    continue
        if self.settings.llm.enabled:
            task = asyncio.create_task(self._refine_decision(event, decision))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
        return decision

    async def _refine_decision(self, event: PrivacyEvent, decision: Decision) -> None:
        from functools import partial

        from privacy_guardian.core.worker_dispatch import refine_context

        try:
            if self.settings.llm.purpose_refinement:
                refined = await asyncio.get_running_loop().run_in_executor(
                    self.llm_executor,
                    partial(
                        refine_context,
                        "purpose_refinement",
                        {
                            "origin": event.requester.origin,
                            "display_name": event.requester.display_name,
                            "purpose": event.requester.purpose,
                        },
                        self.settings.llm.model_dump(),
                        "purpose",
                        {
                            "purpose": event.requester.purpose,
                            "confidence": event.requester.purpose_confidence,
                            "rationale": "Local purpose inference",
                        },
                    ),
                )
                event.requester.purpose = str(refined["purpose"])
                event.requester.purpose_confidence = float(str(refined["confidence"]))
            if self.settings.llm.explanation_polishing and decision.outcome != Outcome.IGNORE:
                polished = await asyncio.get_running_loop().run_in_executor(
                    self.llm_executor,
                    partial(
                        refine_context,
                        "explanation_polishing",
                        {
                            "categories": [category.value for category in event.data_categories],
                            "purpose": event.requester.purpose,
                            "explanation": decision.explanation,
                            "rationale": decision.rationale,
                        },
                        self.settings.llm.model_dump(),
                        "explanation",
                        {"explanation": decision.explanation, "rationale": decision.rationale},
                    ),
                )
                decision.explanation = str(polished["explanation"])
                if isinstance(polished["rationale"], list):
                    decision.rationale = [str(value) for value in polished["rationale"]]
                self.store.save_decision(decision)
                if event.id not in self.actions:
                    for callback in self.decision_listeners:
                        callback(decision)
        except Exception:
            return

    async def _refine_public(
        self, origin: str, digest: str, kind: str, text: str, profile: dict[str, object]
    ) -> None:
        from functools import partial

        from privacy_guardian.llm.enrichment import refine_public_profile

        try:
            enriched = await asyncio.get_running_loop().run_in_executor(
                self.llm_executor,
                partial(refine_public_profile, text, profile, self.settings.llm.model_dump()),
            )
            self.store.cache_document(origin, digest, enriched)
            context = self.contexts.get(origin, {})
            if kind in context.get("analyses", {}):
                context["analyses"][kind]["profile"] = sanitize(enriched)
        except Exception:
            return

    async def respond(self, response: UserResponse) -> dict[str, Any]:
        if response.event_id not in self.decisions:
            raise ValueError("Unknown decision")
        decision = self.decisions[response.event_id]
        if response.action not in ACTIONS or response.action not in decision.actions:
            raise ValueError("Action is not available for this decision")
        if response.event_id in self.actions:
            return self.actions[response.event_id]
        event = self.events[response.event_id]
        result: dict[str, Any] = {"action": response.action, "event_id": event.id}
        if response.action in {"redact", "strip_metadata"}:
            from privacy_guardian.analysis.worker import redact_payload

            if not event.payload_ref:
                raise ValueError("File is no longer available for redaction")
            redacted = await self.pool.run(
                redact_payload, event.payload_ref, None, response.action == "strip_metadata"
            )
            if not redacted.verified:
                raise ValueError("Redaction could not be verified; upload remains cancelled")
            folder = Path.home() / "Downloads/PrivacyGuardian"
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = Path(redacted.filename).name
            target = folder / f"{event.id[:8]}-{name}"
            target.write_bytes(redacted.content)
            target.chmod(0o600)
            result.update(
                {
                    "path": str(target),
                    "filename": name,
                    "mime": redacted.mime,
                    "size": len(redacted.content),
                }
            )
            # Native message cap: extension fetches sanitized artifact in chunks.
            self.actions[event.id] = result
        if response.action == "mark_expected":
            self.preferences.expected_permissions[event.requester.key] = list(
                set(self.preferences.expected_permissions.get(event.requester.key, []))
                | set(event.data_categories)
            )
        if response.remember:
            self.preferences.requester_overrides[event.requester.key] = (
                "allow" if response.action == "continue" else "ask"
            )
        for category in event.data_categories:
            self.learned_rules.record(category, event.requester.purpose, response.action)
        self.store.set_preference("user", self.preferences.model_dump(mode="json"))
        self.store.set_learned_rule("user", self.learned_rules.model_dump(mode="json"))
        self.store.save_response(response)
        if event.payload_ref and response.action in {
            "continue",
            "cancel",
            "redact",
            "strip_metadata",
        }:
            from privacy_guardian.analysis.worker import release_payload

            with contextlib.suppress(RuntimeError, KeyError):
                await self.pool.run(release_payload, event.payload_ref)
            event.payload_ref = None
        self.actions[event.id] = result
        self.pending_since.pop(event.id, None)
        return result

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        request_id = str(message.get("id", ""))[:128]
        try:
            request = Request.model_validate(message)
            result = await self._route(request)
            return {"v": 1, "id": request.id, "ok": True, "result": result, "error": None}
        except (ValidationError, ValueError, KeyError, TypeError, binascii.Error):
            return {
                "v": 1,
                "id": request_id,
                "ok": False,
                "result": None,
                "error": {"code": "invalid_request", "message": "Request failed validation"},
            }
        except Exception:
            return {
                "v": 1,
                "id": request_id,
                "ok": False,
                "result": None,
                "error": {
                    "code": "analysis_unavailable",
                    "message": "Analysis unavailable; please retry",
                },
            }

    async def _route(self, request: Request) -> dict[str, Any]:
        payload = request.payload
        if request.type == "ping":
            browser = str(payload.get("browser", "browser"))[:40]
            self.connected_browsers[browser] = time.monotonic()
            commands, self.browser_commands = self.browser_commands, []
            return {"version": "0.1.0", "protocol": 1, "status": "ready", "commands": commands}
        if request.type == "focus":
            for callback in self.focus_listeners:
                callback()
            return {"focused": True}
        if request.type == "event":
            from privacy_guardian.sensors.browser_bridge import parse_browser_event

            event = parse_browser_event(payload)
            decision = await self.process_event(event)
            return {"decision": decision.model_dump(mode="json")}
        if request.type == "file_start":
            upload_id = str(payload["upload_id"])
            from privacy_guardian.sensors.browser_bridge import enrich_browser_requester

            requester = enrich_browser_requester(
                Requester.model_validate(payload.get("requester", {})), payload.get("signals", {})
            )
            await self.pool.run(
                start_upload,
                upload_id,
                str(payload["filename"]),
                int(payload["size"]),
                str(payload.get("mime", "")),
            )
            self.uploads[upload_id] = {
                "requester": requester,
                "touched": time.monotonic(),
                "size": int(payload["size"]),
                "generation": self.pool.generation,
            }
            return {"upload_id": upload_id}
        if request.type == "file_chunk":
            upload_id = str(payload["upload_id"])
            meta = self.uploads[upload_id]
            if meta["generation"] != self.pool.generation:
                raise ValueError("Worker recycled")
            data = base64.b64decode(str(payload["data"]), validate=True)
            await self.pool.run(append_upload, upload_id, int(payload["sequence"]), data)
            meta["touched"] = time.monotonic()
            return {"received": len(data)}
        if request.type == "file_finish":
            upload_id = str(payload["upload_id"])
            meta = self.uploads.pop(upload_id)
            analysis = await self.pool.run(finish_upload, upload_id)
            event = FileUploadEvent(
                requester=meta["requester"],
                payload_ref=analysis.payload_ref,
                document_type=analysis.document_type,
                partial=analysis.partial,
                size_bytes=meta["size"],
            )
            decision = await self.process_event(event, analysis.findings)
            return {
                "decision": decision.model_dump(mode="json"),
                "findings": [
                    f.model_dump(mode="json", exclude={"span_ref", "stable_hash"})
                    for f in analysis.findings
                ],
                "partial": analysis.partial,
                "warnings": analysis.warnings,
            }
        if request.type == "action":
            return await self.respond(UserResponse.model_validate(payload))
        if request.type == "action_poll":
            event_id = str(payload["event_id"])
            action = self.actions.get(event_id)
            if action and "artifact_offset" in payload and "path" in action:
                offset = int(payload["artifact_offset"])
                if offset < 0:
                    raise ValueError("Invalid artifact offset")
                with Path(action["path"]).open("rb") as handle:
                    handle.seek(offset)
                    data = handle.read(550 * 1024)
                return {
                    "data": base64.b64encode(data).decode("ascii"),
                    "offset": offset,
                    "eof": offset + len(data) >= action["size"],
                }
            return {"pending": action is None, "action": action}
        if request.type == "context":
            from privacy_guardian.sensors.browser_bridge import prepare_context

            payload = prepare_context(payload)
            origin = safe_origin(str(payload.get("origin", "")))
            # Content-bearing context is analysed immediately in the worker.
            from privacy_guardian.analysis.worker import analyze_payload

            profile = self._profile(Requester(origin=origin))
            result: dict[str, Any] = {}
            for kind in ("policy", "terms", "forms", "consent", "tracking"):
                incoming = payload.get(kind)
                if incoming is None:
                    continue
                worker_payload = (
                    dict(incoming) if isinstance(incoming, dict) else {"text": str(incoming)}
                )
                worker_payload.update(
                    {"kind": kind, "purpose": str(payload.get("purpose", "unknown"))}
                )
                analyzed = await self.pool.run(analyze_payload, worker_payload)
                result[kind] = analyzed.model_dump(mode="json", exclude={"payload_ref"})
                if kind in {"policy", "terms"}:
                    digest = hashlib.sha256(
                        str(worker_payload.get("text", "")).encode()
                    ).hexdigest()
                    self.store.cache_document(origin, digest, analyzed.profile)
                    if self.settings.llm.enabled and self.settings.llm.policy_refinement:
                        task = asyncio.create_task(
                            self._refine_public(
                                origin,
                                digest,
                                kind,
                                str(worker_payload.get("text", "")),
                                analyzed.profile,
                            )
                        )
                        self.background_tasks.add(task)
                        task.add_done_callback(self.background_tasks.discard)
                for key, value in analyzed.profile.items():
                    if key == "clauses" and isinstance(value, list):
                        value = [
                            str(item.get("category", "")) if isinstance(item, dict) else str(item)
                            for item in value
                        ]
                    if key in SiteOrAppProfile.model_fields:
                        setattr(profile, key, value)
            self.contexts[origin] = dict(
                sanitize(
                    {
                        "origin": origin,
                        "purpose": payload.get("purpose", "unknown"),
                        "analyses": result,
                    }
                )
            )
            self.store.put_profile("site", origin, profile.model_dump(mode="json"))
            if payload.get("request_id") == self.pending_context_id:
                self.focused_origin = origin
                self.context_updated.set()
            from privacy_guardian.core.events import (
                ConsentBannerEvent,
                PolicyDocumentEvent,
                TrackingEvent,
            )

            requester = Requester.model_validate(payload["requester"])
            for kind, analyzed_result in list(result.items()):
                detail = analyzed_result.get("profile", {})
                context_event: PrivacyEvent | None = None
                if kind == "consent":
                    context_event = ConsentBannerEvent(
                        requester=requester,
                        purposes=detail.get("purposes", []),
                        dark_patterns=detail.get("dark_patterns", []),
                        vendor_count=detail.get("vendor_count", 0),
                        cmp=detail.get("cmp", "unknown"),
                    )
                elif kind == "tracking" and (
                    detail.get("tracker_domains")
                    or detail.get("fingerprinting")
                    or detail.get("signals")
                ):
                    context_event = TrackingEvent(
                        requester=requester,
                        data_categories=[DataCategory.DEVICE_IDENTIFIERS],
                        tracker_domains=detail.get("tracker_domains", []),
                        fingerprinting=detail.get("fingerprinting", False),
                        confidence=detail.get("confidence", 0.5),
                        signals=detail.get("signals", []),
                    )
                elif kind in {"policy", "terms"} and payload.get("trigger_action"):
                    context_event = PolicyDocumentEvent(
                        requester=requester,
                        kind="terms" if kind == "terms" else "privacy_policy",
                        missing=detail.get("missing", False),
                    )
                if context_event:
                    decision = await self.process_event(context_event)
                    analyzed_result["decision"] = decision.model_dump(mode="json")
            return result
        if request.type == "disconnect":
            for event_id in list(self.pending_since):
                self.store.mark_aborted(event_id)
                await self.respond(
                    UserResponse(event_id=event_id, action=self.decisions[event_id].default_action)
                )
            return {"disconnected": True}
        if request.type == "deep_check":
            from privacy_guardian.deepcheck import run_deep_check

            return await run_deep_check(self, payload)
        raise ValueError("Unknown request")

    def pause(self, seconds: int) -> None:
        self.paused_until = datetime.now(UTC) + timedelta(seconds=seconds) if seconds else None
