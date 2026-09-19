from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from privacy_guardian.core.events import (
    DataCategory,
    Decision,
    FormField,
    FormSubmitEvent,
    Outcome,
    Requester,
    UserResponse,
)
from privacy_guardian.storage import Store

SYNTHETIC_CARD = "4111111111111111"
SYNTHETIC_EMAIL = "morgan.testperson@example.test"


def test_store_never_persists_payload_or_form_labels(tmp_path: Path) -> None:
    database = tmp_path / "guardian.sqlite3"
    store = Store(database)
    event = FormSubmitEvent(
        requester=Requester(
            origin=f"https://example.test/form?email={SYNTHETIC_EMAIL}",
            display_name=SYNTHETIC_EMAIL,
        ),
        payload_ref=f"worker-handle:{SYNTHETIC_CARD}",
        data_categories=[DataCategory.FINANCIAL_CARD_NUMBER],
        fields=[
            FormField(
                field_id="card",
                category=DataCategory.FINANCIAL_CARD_NUMBER,
                label=f"Test card {SYNTHETIC_CARD}",
                name=SYNTHETIC_EMAIL,
                filled=True,
            )
        ],
    )
    store.save_event(event)
    dump = "\n".join(store.connection.iterdump())
    store.close()
    assert SYNTHETIC_CARD not in dump
    assert SYNTHETIC_EMAIL not in dump
    assert "worker-handle" not in dump
    assert "financial.card_number" in dump


def test_database_uses_wal_and_private_mode(tmp_path: Path) -> None:
    database = tmp_path / "guardian.sqlite3"
    store = Store(database)
    journal_mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
    store.close()
    assert journal_mode.lower() == "wal"
    if os.name != "nt":
        assert database.stat().st_mode & 0o777 == 0o600


def test_migrates_v1_database_to_current_schema(tmp_path: Path) -> None:
    database = tmp_path / "v1.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_version(version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (1);
        CREATE TABLE events(
          id TEXT PRIMARY KEY, ts TEXT NOT NULL, event_type TEXT NOT NULL,
          requester TEXT NOT NULL, categories TEXT NOT NULL, event_json TEXT NOT NULL
        );
        """
    )
    connection.commit()
    connection.close()
    store = Store(database)
    columns = {row[1] for row in store.connection.execute("PRAGMA table_info(events)")}
    version = store.connection.execute("SELECT version FROM schema_version").fetchone()[0]
    store.close()
    assert "status" in columns
    assert version == Store.SCHEMA_VERSION


def test_purge_removes_old_events_and_preserves_recent(tmp_path: Path) -> None:
    store = Store(tmp_path / "purge.sqlite3")
    old = FormSubmitEvent(ts=datetime.now(UTC) - timedelta(days=91))
    recent = FormSubmitEvent(ts=datetime.now(UTC) - timedelta(days=89))
    store.save_event(old)
    store.save_event(recent)
    assert store.purge(days=90) == 1
    history = store.history()
    store.close()
    assert [item["event"]["id"] for item in history] == [recent.id]


def test_preferences_export_import_round_trip(tmp_path: Path) -> None:
    first = Store(tmp_path / "first.sqlite3")
    first.set_preference("phone:saas_b2b", {"behaviour": "ask"})
    first.set_learned_rule("email:news", {"outcome": "INFORM", "count": 3})
    payload = first.export_preferences()
    first.close()
    second = Store(tmp_path / "second.sqlite3")
    second.import_preferences(payload)
    assert second.export_preferences() == payload
    second.close()


def test_repeated_event_save_preserves_decision_and_response(tmp_path: Path) -> None:
    store = Store(tmp_path / "upsert.sqlite3")
    event = FormSubmitEvent()
    store.save_event(event)
    store.save_decision(
        Decision(
            event_id=event.id,
            outcome=Outcome.INFORM,
            risk=0.4,
            explanation="Synthetic notice",
            actions=["continue"],
            default_action="continue",
        )
    )
    store.save_response(UserResponse(event_id=event.id, action="continue"))
    store.save_event(event.model_copy(update={"platform": "updated"}))
    counts = store.diagnostics()
    store.close()
    assert counts["events"] == 1
    assert counts["decisions"] == 1
    assert counts["user_responses"] == 1


def test_refuses_database_from_newer_schema(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version={Store.SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(ValueError, match="newer"):
        Store(database)
