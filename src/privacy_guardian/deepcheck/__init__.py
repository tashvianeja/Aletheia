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


def _sentence_list(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _named(categories: list[Any]) -> list[str]:
    """Data categories as a reader would say them, lower case for mid-sentence use."""
    from privacy_guardian.engine.labels import category_label, lowered

    named = [lowered(category_label(str(category))) for category in categories if category]
    return list(dict.fromkeys(named))


def _finding(
    kind: str, severity: str, summary: str, detail: str = "", tone: str = "warn"
) -> dict[str, Any]:
    """One row of the report. `tone` is how it is drawn; `severity` is what it triggers.

    A liability cap and "your data can be sold" are both worth knowing and are not worth
    the same triangle, so the ordinary machinery of a contract is reported as a note.
    """
    return {"kind": kind, "severity": severity, "summary": summary, "detail": detail, "tone": tone}


def _clause_findings(kind: str, profile: dict[str, Any], seen: set[str]) -> list[dict[str, Any]]:
    """What the document's clauses mean, said once each however many documents say it."""
    from privacy_guardian.engine.clauses import clause_meaning, clause_title, is_material

    rows: list[dict[str, Any]] = []
    for clause in profile.get("clauses", []):
        category = clause.get("category", "") if isinstance(clause, dict) else str(clause)
        if not category or category in seen:
            continue
        seen.add(category)
        rows.append(
            _finding(
                kind,
                "INFORM",
                clause_title(category),
                clause_meaning(category),
                tone="warn" if is_material(category) else "info",
            )
        )
    return rows


def build_groups(
    findings: list[dict[str, Any]], checked: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fold flat findings into the four report sections, filling in the all-clears."""
    availability = {item["kind"]: item for item in checked}
    groups: list[dict[str, Any]] = []
    for key, title, kinds in GROUPS:
        rows = [
            {
                "severity": finding.get("tone", "warn"),
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
    # A policy and a set of terms usually repeat one another. Say each clause once.
    seen_clauses: set[str] = set()
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
            # Retention after deletion is a clause, and the clause says it in better
            # words. This stands in only where the profile knows it some other way.
            if profile.get("retention") == "after_deletion" and not any(
                (clause.get("category") if isinstance(clause, dict) else clause)
                == "retention_after_deletion"
                for clause in profile.get("clauses", [])
            ):
                findings.append(
                    _finding(
                        "policy",
                        "INFORM",
                        "Deleting your account does not delete your data",
                        "Copies can be kept after you close the account or delete the file.",
                    )
                )
            over = _named(profile.get("over_collection", []))
            if over:
                # One sentence for the whole list. A finding per category was the same
                # headline five times over, each with a different noun under it.
                findings.append(
                    _finding(
                        "policy",
                        "INFORM",
                        "The privacy policy claims more than this site appears to need",
                        f"It says it collects {_sentence_list(over)}.",
                    )
                )
            findings.extend(_clause_findings("policy", profile, seen_clauses))
        elif name == "terms":
            findings.extend(_clause_findings("terms", profile, seen_clauses))
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
            asked = [
                field
                for field in analysis.get("fields", [])
                if (field.get("necessity") or {}).get("verdict") in {"unnecessary", "red_flag"}
            ]
            serious = [
                field
                for field in asked
                if (field.get("necessity") or {}).get("verdict") == "red_flag"
            ]
            if asked:
                names = _named(
                    [(field.get("necessity") or {}).get("category", "") for field in asked]
                )
                findings.append(
                    _finding(
                        "forms",
                        "INTERVENE" if serious else "INFORM",
                        "This form asks for "
                        + (
                            "things it has no business asking for"
                            if serious
                            else "more than it needs"
                        ),
                        f"It asks for {_sentence_list(names)}. "
                        + (
                            str((asked[0].get("necessity") or {}).get("rationale", ""))
                            if len(asked) == 1
                            else "None of these is needed for what this form does."
                        ),
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
    # Questions first, then the things worth knowing, then the ordinary machinery.
    findings.sort(key=lambda item: (item["severity"] != "INTERVENE", item.get("tone") != "warn"))
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
