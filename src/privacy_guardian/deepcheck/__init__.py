from __future__ import annotations

import asyncio
import time
from typing import Any

from privacy_guardian.core.events import Outcome
from privacy_guardian.util.i18n import tr


async def run_deep_check(service: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    started = time.monotonic()
    fresh = True
    for callback in service.progress_listeners:
        callback(tr("checking"))
    if service.connected_browsers and not payload.get("cached_only"):
        from uuid import uuid4

        service.context_updated.clear()
        service.pending_context_id = str(uuid4())
        service.browser_commands.append(
            {"id": service.pending_context_id, "type": "collect_context"}
        )
        try:
            await asyncio.wait_for(service.context_updated.wait(), timeout=3.0)
        except TimeoutError:
            fresh = False
    origin = str(payload.get("origin", "")) or service.focused_origin
    context: dict[str, Any] = (
        service.contexts.get(origin, {}) if (fresh or payload.get("cached_only")) else {}
    )
    findings: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    analyses = context.get("analyses", {})
    for name in ("tracking", "consent", "policy", "terms", "forms", "uploads"):
        analysis = analyses.get(name, {})
        profile = analysis.get("profile", {})
        if name == "tracking" and (
            profile.get("fingerprinting")
            or profile.get("tracker_domains")
            or profile.get("tracking_confidence", 0) > 0.2
        ):
            findings.append(
                {
                    "kind": "tracking",
                    "severity": "INFORM",
                    "summary": "Advertising profile detected",
                }
            )
        elif name == "consent" and profile.get("dark_patterns"):
            findings.append(
                {
                    "kind": "consent",
                    "severity": "INTERVENE",
                    "summary": "Cookie choices make rejecting optional tracking harder",
                }
            )
        elif name == "policy":
            if profile.get("missing"):
                findings.append(
                    {"kind": "policy", "severity": "INFORM", "summary": "No privacy policy found"}
                )
            if profile.get("retention") == "after_deletion":
                findings.append(
                    {
                        "kind": "policy",
                        "severity": "INFORM",
                        "summary": "Data may be retained after account deletion",
                    }
                )
            for statement in profile.get("necessity_statements", []):
                if (
                    "unnecessary" in statement.lower()
                    or "not appear necessary" in statement.lower()
                    or "does not" in statement.lower()
                ):
                    findings.append({"kind": "policy", "severity": "INFORM", "summary": statement})
            for clause in profile.get("clauses", []):
                category = clause.get("category", "") if isinstance(clause, dict) else str(clause)
                if category in {"data_sale", "training_on_user_content", "third_party_sharing"}:
                    findings.append(
                        {
                            "kind": "policy",
                            "severity": "INFORM",
                            "summary": category.replace("_", " ").capitalize(),
                        }
                    )
        elif name == "terms":
            for clause in profile.get("clauses", []):
                category = clause.get("category", "") if isinstance(clause, dict) else str(clause)
                if category and not any(
                    category.replace("_", " ").lower() in item["summary"].lower()
                    for item in findings
                ):
                    findings.append(
                        {
                            "kind": "terms",
                            "severity": "INFORM",
                            "summary": category.replace("_", " ").capitalize(),
                        }
                    )
        elif name == "uploads" and profile.get("in_progress", 0):
            findings.append(
                {
                    "kind": "uploads",
                    "severity": "INFORM",
                    "summary": "Files are selected for sharing; review their upload decisions",
                }
            )
        elif name == "forms":
            for field in analysis.get("fields", []):
                if (field.get("necessity") or {}).get("verdict") in {"unnecessary", "red_flag"}:
                    findings.append(
                        {
                            "kind": "forms",
                            "severity": "INFORM",
                            "summary": str(
                                (field.get("necessity") or {}).get(
                                    "rationale", "A field may be unnecessary"
                                )
                            ),
                        }
                    )
        checked.append(
            {
                "kind": name,
                "clean": bool(analysis) and not any(f["kind"] == name for f in findings),
                "available": bool(analysis),
            }
        )
    if service.adapter:
        for event in await asyncio.to_thread(service.adapter.snapshot):
            from privacy_guardian.engine.decision import decide

            decision = decide(
                event,
                preferences=service.preferences_for(event.requester),
                learned_rules=service.learned_rules,
            )
            if decision.outcome != Outcome.IGNORE:
                findings.append(
                    {
                        "kind": event.event_type,
                        "severity": str(decision.outcome),
                        "summary": decision.explanation,
                    }
                )
        checked.append(
            {
                "kind": "permissions",
                "clean": not any(f["kind"] == "permission_request" for f in findings),
                "available": True,
            }
        )
    findings.sort(key=lambda item: item["severity"] != "INTERVENE")
    report: dict[str, Any] = {
        "origin": context.get("origin", origin),
        "findings": findings,
        "checked": checked,
        "summary": tr("check_summary", count=len(findings)),
        "context_available": bool(context) or service.adapter is not None,
        "fresh": fresh,
    }

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
