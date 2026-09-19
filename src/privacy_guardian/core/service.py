from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import logging
import multiprocessing
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import partial
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
from privacy_guardian.util.privacy import public_identity, safe_origin, sanitize


class Service:
    def __init__(self, settings: Settings, store: Store | None = None) -> None:
        self.settings = settings
        self.store = store or Store(settings.data_dir / "guardian.sqlite3")
        self.bus = EventBus()
        self.pool = AnalysisPool(settings.analysis_timeout_seconds)
        self.control = ControlServer(settings.data_dir, self.handle_message)
        self.metadata_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="guardian-metadata"
        )
        self.metadata_slots = asyncio.Semaphore(8)
        self.preferences = UserPreferences.model_validate(
            self.store.get_preferences().get("user", {})
        )
        self.preferences.reject_optional_cookies = settings.reject_optional_cookies
        self.preferences.clipboard_allowlist = list(
            dict.fromkeys([*self.preferences.clipboard_allowlist, *settings.clipboard_allowlist])
        )
        self.learned_rules = LearnedRules.model_validate(
            self.store.get_learned_rules().get("user", {})
        )
        self.decision_listeners: list[Callable[[Decision], None]] = []
        self.focus_listeners: list[Callable[[], None]] = []
        self.action_listeners: list[Callable[[str, str], None]] = []
        self.progress_listeners: list[Callable[[str], None]] = []
        self.events: dict[str, PrivacyEvent] = {}
        self.decisions: dict[str, Decision] = {}
        self.actions: dict[str, dict[str, Any]] = {}
        self.pending_since: dict[str, float] = {}
        self.event_owners: dict[str, str] = {}
        self.response_locks: dict[str, asyncio.Lock] = {}
        self.cloud_keys: set[str] = set()
        self.uploads: dict[str, dict[str, Any]] = {}
        self.contexts: dict[str, dict[str, Any]] = {}
        self.browser_commands: list[dict[str, Any]] = []
        self.context_updated = asyncio.Event()
        self.pending_context_id: str | None = None
        self.focused_origin = ""
        self.connected_browsers: dict[str, float] = {}
        self.paused_until: datetime | None = None
        self.adapter: Any = None
        self._llm_executor: ProcessPoolExecutor | None = None
        self.cloud_last_used = time.monotonic()
        self.background_tasks: set[asyncio.Task[None]] = set()
        self._sweeper: asyncio.Task[None] | None = None

    @property
    def llm_executor(self) -> ProcessPoolExecutor:
        if self._llm_executor is None:
            self._llm_executor = ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
        self.cloud_last_used = time.monotonic()
        return self._llm_executor

    def _close_cloud(self) -> None:
        executor, self._llm_executor = self._llm_executor, None
        if executor:
            for process in (getattr(executor, "_processes", {}) or {}).values():
                if process.is_alive():
                    process.terminate()
            executor.shutdown(wait=False, cancel_futures=True)

    def _schedule_cloud(self, key: str, factory: Callable[[], Any]) -> None:
        if (
            not self.settings.llm.enabled
            or key in self.cloud_keys
            or len(self.background_tasks) >= 4
        ):
            return
        self.cloud_keys.add(key)

        async def run() -> None:
            try:
                if self.settings.llm.enabled:
                    await factory()
            finally:
                self.cloud_keys.discard(key)
                self.cloud_last_used = time.monotonic()

        task = asyncio.create_task(run())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def start(self) -> None:
        await self.control.start()
        self.bus.subscribe(self._on_event)
        self.store.purge(self.settings.retention_days)
        self._sweeper = asyncio.create_task(self._maintenance())

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
        self._close_cloud()
        self.metadata_executor.shutdown(wait=False, cancel_futures=True)
        self.pool.close()
        self.store.close()

    async def _on_event(self, event: PrivacyEvent) -> None:
        await self.process_event(event)

    async def _maintenance(self) -> None:
        while True:
            await asyncio.sleep(1)
            try:
                await self.control.ensure_running()
                now = time.monotonic()
                if not self.settings.llm.enabled:
                    for task in tuple(self.background_tasks):
                        task.cancel()
                    self._close_cloud()
                elif not self.background_tasks and now - self.cloud_last_used > 30:
                    self._close_cloud()
                if (
                    self.pool._pool is not None
                    and not self.pool.active
                    and not self.uploads
                    and now - self.pool.last_used
                    > (120 if any(event.payload_ref for event in self.events.values()) else 10)
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
            except Exception as error:
                logging.getLogger(__name__).warning(
                    "maintenance_recovered", extra={"error_type": type(error).__name__}
                )

    def _profile(self, requester: Requester) -> SiteOrAppProfile:
        kind = "site" if requester.kind == "website" else "app"
        return SiteOrAppProfile.model_validate(self.store.get_profile(kind, requester.key) or {})

    def preferences_for(self, requester: Requester) -> UserPreferences:
        preferences = self.preferences.model_copy(deep=True)
        public_key = public_identity(requester.key)
        if public_key in preferences.requester_overrides:
            preferences.requester_overrides[requester.key] = preferences.requester_overrides[
                public_key
            ]
        if public_key in preferences.expected_permissions:
            preferences.expected_permissions[requester.key] = preferences.expected_permissions[
                public_key
            ]
        return preferences

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
        decision = decide(
            event, findings, profile, self.preferences_for(event.requester), self.learned_rules
        )
        if self.paused_until and datetime.now(UTC) < self.paused_until:
            decision = decision.model_copy(
                update={
                    "outcome": Outcome.IGNORE,
                    "explanation": "Monitoring is paused.",
                    "actions": ["continue"],
                    "default_action": "continue",
                }
            )
        if event.event_type == "policy_document":
            kind = "terms" if getattr(event, "kind", "") == "terms" else "policy"
            document = (
                self.contexts.get(event.requester.origin, {})
                .get("analyses", {})
                .get(kind, {})
                .get("profile", {})
            )
            for clause in document.get("clauses", []):
                if isinstance(clause, dict):
                    title = str(clause.get("category", "")).replace("_", " ").capitalize()
                    citation = str(clause.get("citation", ""))
                    decision.rationale.append(title + (": " + citation if citation else ""))
            decision.rationale.extend(
                "✓ Nothing unusual about " + str(item).replace("_", " ")
                for item in document.get("nothing_unusual", [])
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
        if self.settings.llm.enabled and event.event_type != "form_observed":
            self._schedule_cloud(
                event.requester.key + ":" + event.event_type,
                lambda: self._refine_decision(event, decision),
            )
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
                reassessed = decide(
                    event,
                    profile=self._profile(event.requester),
                    preferences=self.preferences,
                    learned_rules=self.learned_rules,
                )
                levels = {Outcome.IGNORE: 0, Outcome.INFORM: 1, Outcome.INTERVENE: 2}
                if levels[reassessed.outcome] >= levels[decision.outcome]:
                    decision = reassessed
                    self.decisions[event.id] = decision
                self.store.save_event(event)
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
            cached = self.store.get_cached_document(origin, digest) or {}
            self.store.cache_document(origin, digest, {**cached, kind: enriched})
            context = self.contexts.get(origin, {})
            if kind in context.get("analyses", {}):
                context["analyses"][kind]["profile"] = sanitize(enriched)
        except Exception:
            return

    async def respond(self, response: UserResponse) -> dict[str, Any]:
        lock = self.response_locks.setdefault(response.event_id, asyncio.Lock())
        async with lock:
            return await self._respond_once(response)

    async def _respond_once(self, response: UserResponse) -> dict[str, Any]:
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
            self.preferences.expected_permissions[public_identity(event.requester.key)] = list(
                set(
                    self.preferences.expected_permissions.get(
                        public_identity(event.requester.key), []
                    )
                )
                | set(event.data_categories)
            )
        if response.remember:
            self.preferences.requester_overrides[public_identity(event.requester.key)] = (
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
        for callback in self.action_listeners:
            callback(event.id, response.action)
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
        payload = dict(request.payload)
        session = str(payload.pop("_session", ""))[:128]
        if request.type == "ping":
            browser = str(payload.get("browser", "browser"))[:40]
            self.connected_browsers[browser] = time.monotonic()
            commands, self.browser_commands = self.browser_commands, []
            from privacy_guardian import __version__

            return {"version": __version__, "protocol": 1, "status": "ready", "commands": commands}
        if request.type == "focus":
            for callback in self.focus_listeners:
                callback()
            return {"focused": True}
        if request.type == "event":
            from privacy_guardian.sensors.browser_bridge import parse_browser_event

            event = parse_browser_event(payload)
            decision = await self.process_event(event)
            self.event_owners[event.id] = session
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
                "session": session,
            }
            return {"upload_id": upload_id}
        if request.type == "file_chunk":
            upload_id = str(payload["upload_id"])
            meta = self.uploads[upload_id]
            if meta["session"] != session or meta["generation"] != self.pool.generation:
                raise ValueError("Worker recycled")
            data = base64.b64decode(str(payload["data"]), validate=True)
            await self.pool.run(append_upload, upload_id, int(payload["sequence"]), data)
            meta["touched"] = time.monotonic()
            return {"received": len(data)}
        if request.type == "file_finish":
            upload_id = str(payload["upload_id"])
            meta = self.uploads[upload_id]
            if meta["session"] != session or meta["generation"] != self.pool.generation:
                raise ValueError("Upload session is no longer valid")
            self.uploads.pop(upload_id)
            analysis = await self.pool.run(
                finish_upload, upload_id, self.settings.analysis_timeout_seconds
            )
            event = FileUploadEvent(
                requester=meta["requester"],
                payload_ref=analysis.payload_ref,
                document_type=analysis.document_type,
                partial=analysis.partial,
                size_bytes=meta["size"],
            )
            decision = await self.process_event(event, analysis.findings)
            self.event_owners[event.id] = session
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
            if session and self.event_owners.get(str(payload.get("event_id", ""))) != session:
                raise ValueError("Decision belongs to a different session")
            return await self.respond(UserResponse.model_validate(payload))
        if request.type == "action_poll":
            event_id = str(payload["event_id"])
            if session and self.event_owners.get(event_id) != session:
                raise ValueError("Decision belongs to a different session")
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
                from privacy_guardian.analysis.worker import AnalysisResult

                digest = (
                    hashlib.sha256(str(worker_payload.get("text", "")).encode()).hexdigest()
                    if kind in {"policy", "terms"}
                    else ""
                )
                cached = self.store.get_cached_document(origin, digest) if digest else None
                if cached is not None and isinstance(cached.get(kind), dict):
                    analyzed = AnalysisResult(profile=cached[kind])
                    if kind == "policy":
                        from privacy_guardian.engine.necessity import necessity_for

                        purpose = str(payload.get("purpose", "unknown"))
                        collected = analyzed.profile.get("collects", [])
                        analyzed.profile["necessity_statements"] = [
                            f"Collects {category.value.replace('_', ' ').replace('.', ' ')}: {necessity_for(purpose, category).rationale}"
                            for category in map(
                                DataCategory, collected if isinstance(collected, list) else []
                            )
                        ]
                elif kind in {"forms", "consent", "tracking"}:
                    if self.metadata_slots.locked():
                        raise ValueError("Metadata analysis queue is full")
                    async with self.metadata_slots:
                        analyzed = await asyncio.get_running_loop().run_in_executor(
                            self.metadata_executor, analyze_payload, worker_payload
                        )
                else:
                    analyzed = await self.pool.run(analyze_payload, worker_payload)
                result[kind] = analyzed.model_dump(mode="json", exclude={"payload_ref"})
                if kind in {"policy", "terms"}:
                    digest = hashlib.sha256(
                        str(worker_payload.get("text", "")).encode()
                    ).hexdigest()
                    cached = self.store.get_cached_document(origin, digest) or {}
                    self.store.cache_document(origin, digest, {**cached, kind: analyzed.profile})
                    if self.settings.llm.enabled and self.settings.llm.policy_refinement:
                        self._schedule_cloud(
                            origin + ":" + digest,
                            partial(
                                self._refine_public,
                                origin,
                                digest,
                                kind,
                                str(worker_payload.get("text", "")),
                                analyzed.profile,
                            ),
                        )
            if "uploads_in_progress" in payload:
                result["uploads"] = {
                    "profile": {"in_progress": max(0, int(payload["uploads_in_progress"]))}
                }
            combined_analyses = {**self.contexts.get(origin, {}).get("analyses", {}), **result}
            # Reload only after worker awaits: concurrent contexts and event observations
            # may have updated the profile while this analysis was running.
            profile = self._profile(Requester(origin=origin))
            for completed in combined_analyses.values():
                for key, value in completed.get("profile", {}).items():
                    if key == "clauses":
                        continue
                    if key in SiteOrAppProfile.model_fields:
                        setattr(profile, key, value)
            clauses: set[str] = set()
            for document_kind in ("policy", "terms"):
                document_profile = combined_analyses.get(document_kind, {}).get("profile", {})
                clauses.update(
                    str(item.get("category", "")) if isinstance(item, dict) else str(item)
                    for item in document_profile.get("clauses", [])
                )
            profile.clauses = sorted(clauses)
            profile.training_on_user_content = "training_on_user_content" in clauses
            profile.data_sale = "data_sale" in clauses
            profile.international_transfer = (
                profile.international_transfer or "cross_border_transfer" in clauses
            )
            if "retention_after_deletion" in clauses:
                profile.retention = "after_deletion"
            profile.policy_missing = bool(
                combined_analyses.get("policy", {}).get("profile", {}).get("missing", False)
            )
            tracking_profile = combined_analyses.get("tracking", {}).get("profile", {})
            profile.tracking_confidence = float(tracking_profile.get("confidence", 0))
            self.contexts[origin] = dict(
                sanitize(
                    {
                        "origin": origin,
                        "purpose": payload.get("purpose", "unknown"),
                        "analyses": combined_analyses,
                        "updated_at": time.monotonic(),
                        "session": session,
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
                    self.event_owners[context_event.id] = session
                    analyzed_result["decision"] = decision.model_dump(mode="json")
            return result
        if request.type == "disconnect":
            if not session:
                raise ValueError("Disconnect requires a host session")
            requested_event = str(payload.get("event_id", ""))
            if requested_event:
                if self.event_owners.get(requested_event) != session:
                    raise ValueError("Decision belongs to a different session")
                self.store.mark_aborted(requested_event)
                if requested_event in self.pending_since:
                    await self.respond(
                        UserResponse(
                            event_id=requested_event,
                            action=self.decisions[requested_event].default_action,
                        )
                    )
                return {"disconnected": True, "event_id": requested_event}
            for upload_id, metadata in list(self.uploads.items()):
                if metadata["session"] == session:
                    with contextlib.suppress(RuntimeError, KeyError):
                        await self.pool.run(abort_upload, upload_id)
                    self.uploads.pop(upload_id, None)
            for event_id in list(self.pending_since):
                if self.event_owners.get(event_id) != session:
                    continue
                self.store.mark_aborted(event_id)
                await self.respond(
                    UserResponse(event_id=event_id, action=self.decisions[event_id].default_action)
                )
            for origin, context in list(self.contexts.items()):
                if context.get("session") == session:
                    self.contexts.pop(origin, None)
            return {"disconnected": True}
        if request.type == "deep_check":
            from privacy_guardian.deepcheck import run_deep_check

            return await run_deep_check(self, payload)
        raise ValueError("Unknown request")

    def pause(self, seconds: int) -> None:
        self.paused_until = datetime.now(UTC) + timedelta(seconds=seconds) if seconds else None
