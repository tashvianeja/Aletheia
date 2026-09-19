from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from privacy_guardian.core.events import Outcome, Requester
from privacy_guardian.util.i18n import tr

# The four things a thorough check reports on, in the order the mockups show them.
GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("permissions", "Permissions", ("permissions", "system_access", "permission_request")),
    ("tracking", "Tracking", ("tracking", "consent", "clipboard_read", "screen_capture")),
    ("policy", "Privacy policy", ("policy", "terms")),
    ("forms", "Current form", ("forms", "uploads")),
)
# What a clean section says, so an all-clear is as readable as a warning.
CLEAN = {
    "permissions": (
        "No unnecessary permissions found",
        "Nothing is asking for more access than it appears to need.",
    ),
    "tracking": (
        "No advertising profile detected",
        "Nothing on this page links your activity to other websites.",
    ),
    "policy": (
        "Nothing unusual in the policy",
        "Collection, sharing and retention read as ordinary for this kind of service.",
    ),
    "forms": (
        "No sensitive file currently shared",
        "Nothing in this page's forms or uploads contains identity or payment information.",
    ),
}
UNAVAILABLE = {
    "permissions": "Desktop monitoring did not report in time.",
    "tracking": "No page context was available to check.",
    "policy": "No policy or terms document was found to read.",
    "forms": "No form or upload control is present on this page.",
}


def _finding(kind: str, severity: str, summary: str, detail: str = "") -> dict[str, Any]:
    return {"kind": kind, "severity": severity, "summary": summary, "detail": detail}


def build_groups(
    findings: list[dict[str, Any]], checked: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fold flat findings into the four report sections, filling in the all-clears."""
    availability = {item["kind"]: item for item in checked}
    groups: list[dict[str, Any]] = []
    for key, title, kinds in GROUPS:
        rows = [
            {
                "severity": "warn",
                "summary": finding["summary"],
                "detail": finding.get("detail", ""),
            }
            for finding in findings
            if finding["kind"] in kinds
        ]
        available = any(availability.get(kind, {}).get("available") for kind in kinds)
        if not rows:
            if available:
                summary, detail = CLEAN[key]
                rows = [{"severity": "ok", "summary": summary, "detail": detail}]
            else:
                rows = [
                    {"severity": "info", "summary": tr("not_observed"), "detail": UNAVAILABLE[key]}
                ]
        groups.append({"key": key, "title": title, "rows": rows, "available": available})
    return groups


async def run_deep_check(
    service: Any,
    payload: dict[str, Any] | None = None,
    *,
    foreground_requester: Requester | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    started = time.monotonic()
    fresh = True
    foreground = foreground_requester
    browser_foreground = True
    if service.adapter and hasattr(service.adapter, "foreground_requester"):
        if foreground is None:
            foreground = Requester.model_validate(
                await asyncio.to_thread(service.adapter.foreground_requester)
            )
        identity = (
            foreground.display_name + " " + foreground.bundle_id + " " + foreground.exe_path
        ).lower()
        browser_foreground = any(
            name in identity
            for name in ("chrome", "chromium", "firefox", "safari", "edge", "brave", "browser")
        )

    def progress(stage: str, state: str) -> None:
        for callback in service.progress_listeners:
            callback({"stage": stage, "state": state})

    progress("start", "running")
    if browser_foreground and service.connected_browsers and not payload.get("cached_only"):
        from uuid import uuid4

        service.context_updated.clear()
        service.pending_context_id = str(uuid4())
        service.browser_commands.append(
            {"id": service.pending_context_id, "type": "collect_context"}
        )
        try:
            await asyncio.wait_for(service.context_updated.wait(), timeout=8.0)
        except TimeoutError:
            fresh = False
    origin = str(payload.get("origin", "")) or service.focused_origin
    context: dict[str, Any] = (
        service.contexts.get(origin, {})
        if browser_foreground and (fresh or payload.get("cached_only"))
        else {}
    )
    findings: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    analyses = context.get("analyses", {})
    for name in ("tracking", "consent", "policy", "terms", "forms", "uploads"):
        analysis = analyses.get(name, {})
        profile = analysis.get("profile", {})
        if analysis.get("partial") or profile.get("partial"):
            findings.append(
                _finding(
                    name,
                    "INFORM",
                    "Document analysis is partial",
                    "Some of the document could not be read, so part of it has not been checked.",
                )
            )
        if name == "tracking" and (
            profile.get("fingerprinting")
            or profile.get("tracker_domains")
            or profile.get("tracking_confidence", 0) > 0.2
        ):
            others = len(profile.get("tracker_domains", []))
            findings.append(
                _finding(
                    "tracking",
                    "INFORM",
                    "Advertising profile",
                    "Your activity may be used for personalised advertising"
                    + (
                        f", linked across {others} other "
                        f"{'company' if others == 1 else 'companies'}."
                        if others
                        else "."
                    ),
                )
            )
        elif name == "consent" and profile.get("dark_patterns"):
            findings.append(
                _finding(
                    "consent",
                    "INTERVENE",
                    "Cookie choices are weighted against you",
                    "Rejecting optional tracking takes more steps than accepting it.",
                )
            )
        elif name == "policy":
            if profile.get("missing"):
                findings.append(
                    _finding(
                        "policy",
                        "INFORM",
                        "No privacy policy found",
                        "What is collected, shared and kept could not be checked.",
                    )
                )
            if profile.get("retention") == "after_deletion":
                findings.append(
                    _finding(
                        "policy",
                        "INFORM",
                        "Data retention",
                        "Uploaded files may be kept after you delete them.",
                    )
                )
            for statement in profile.get("necessity_statements", []):
                if (
                    "unnecessary" in statement.lower()
                    or "not appear necessary" in statement.lower()
                    or "does not" in statement.lower()
                ):
                    findings.append(
                        _finding("policy", "INFORM", "Collects more than it needs", statement)
                    )
            for clause in profile.get("clauses", []):
                category = clause.get("category", "") if isinstance(clause, dict) else str(clause)
                if category in {"data_sale", "training_on_user_content", "third_party_sharing"}:
                    findings.append(
                        _finding(
                            "policy",
                            "INFORM",
                            category.replace("_", " ").capitalize(),
                            str(clause.get("citation", "")) if isinstance(clause, dict) else "",
                        )
                    )
        elif name == "terms":
            for clause in profile.get("clauses", []):
                category = clause.get("category", "") if isinstance(clause, dict) else str(clause)
                if category and not any(
                    category.replace("_", " ").lower() in item["summary"].lower()
                    for item in findings
                ):
                    findings.append(
                        _finding(
                            "terms",
                            "INFORM",
                            category.replace("_", " ").capitalize(),
                            str(clause.get("citation", "")) if isinstance(clause, dict) else "",
                        )
                    )
        elif name == "uploads" and profile.get("in_progress", 0):
            findings.append(
                _finding(
                    "uploads",
                    "INFORM",
                    "Files are selected for sharing",
                    "Review their upload decisions before this page sends them.",
                )
            )
        elif name == "forms":
            for field in analysis.get("fields", []):
                necessity = field.get("necessity") or {}
                if necessity.get("verdict") in {"unnecessary", "red_flag"}:
                    findings.append(
                        _finding(
                            "forms",
                            "INFORM",
                            "This form asks for more than it needs",
                            str(necessity.get("rationale", "")),
                        )
                    )
        checked.append(
            {
                "kind": name,
                "clean": bool(analysis) and not any(f["kind"] == name for f in findings),
                "available": bool(analysis),
            }
        )
        progress(name, "done" if analysis else "unavailable")
    if service.adapter:
        before_desktop = len(findings)
        try:
            desktop_events = await asyncio.wait_for(
                asyncio.to_thread(service.adapter.snapshot, foreground)
                if foreground is not None
                else asyncio.to_thread(service.adapter.snapshot),
                timeout=max(0.1, 9.5 - time.monotonic() + started),
            )
            desktop_available = True
        except TimeoutError:
            desktop_events = []
            desktop_available = False
            fresh = False
        desktop_events.extend(
            event
            for event in getattr(service, "events", {}).values()
            if event.event_type in {"clipboard_read", "screen_capture"}
            and (datetime.now(UTC) - event.ts).total_seconds() < 300
        )
        observed_ids: set[str] = set()
        for event in desktop_events:
            if event.id in observed_ids or (
                foreground is not None and event.requester.key != foreground.key
            ):
                continue
            observed_ids.add(event.id)
            from privacy_guardian.engine.decision import decide

            decision = decide(
                event,
                profile=service._profile(event.requester),
                preferences=service.preferences_for(event.requester),
                learned_rules=service.learned_rules,
            )
            if decision.outcome != Outcome.IGNORE:
                findings.append(
                    _finding(
                        event.event_type,
                        str(decision.outcome),
                        decision.headline or decision.explanation,
                        decision.body,
                    )
                )
        checked.append(
            {
                "kind": "permissions",
                "clean": desktop_available and len(findings) == before_desktop,
                "available": desktop_available,
            }
        )
        progress("permissions", "done" if desktop_available else "unavailable")
    findings.sort(key=lambda item: item["severity"] != "INTERVENE")
    count = len(findings)
    report: dict[str, Any] = {
        "origin": context.get("origin", origin) or (foreground.display_name if foreground else ""),
        "ran_at": datetime.now(UTC).isoformat(),
        "findings": findings,
        "checked": checked,
        "groups": build_groups(findings, checked),
        "summary": (
            tr("check_summary", count=count)
            if count > 1
            else tr("check_summary_one")
            if count
            else tr("check_clean")
        ),
        "context_available": bool(context) or service.adapter is not None,
        "fresh": fresh,
    }
    progress("complete", "done")

    if service.settings.llm.enabled and service.settings.llm.deep_check_narrative:
        from functools import partial

        from privacy_guardian.core.worker_dispatch import refine_context

        try:
            narrative = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    service.llm_executor,
                    partial(
                        refine_context,
                        "deep_check_narrative",
                        {"findings": findings, "checked": checked},
                        service.settings.llm.model_dump(),
                        "deep_check",
                        {
                            "summary": report["summary"],
                            "findings": [item["summary"] for item in findings],
                            "clean_checks": [item["kind"] for item in checked if item["clean"]],
                        },
                    ),
                ),
                timeout=max(0.1, 24 - time.monotonic() + started),
            )
            report["summary"] = narrative["summary"]
        except (TimeoutError, RuntimeError):
            pass

    return report
