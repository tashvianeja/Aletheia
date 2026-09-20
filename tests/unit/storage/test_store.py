from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from privacy_guardian.core.events import (
    ConsentBannerEvent,
    DataCategory,
    Decision,
    FileUploadEvent,
    FormField,
    FormSubmitEvent,
    Outcome,
    PermissionRequestEvent,
    Requester,
    TrackingEvent,
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


def _decide(store: Store, event_id: str, outcome: Outcome, auto_action: str = "") -> None:
    store.save_decision(
        Decision(
            event_id=event_id,
            outcome=outcome,
            risk=0.5,
            explanation="Synthetic",
            actions=["reject_optional", "continue", "cancel"],
            auto_action=auto_action,
        )
    )


def test_tally_counts_each_thing_once_and_only_what_finished(tmp_path: Path) -> None:
    """The Overview's numbers come from the records, and never inflate them.

    The same page reports its trackers on every load, the desktop polls the same grant
    every few seconds, an upload can be abandoned before it was checked, and a "policy"
    row can record that no policy was found. None of those may count.
    """
    store = Store(tmp_path / "tally.sqlite3")
    news = Requester(origin="https://news.example", display_name="news")
    shop = Requester(origin="https://shop.example", display_name="shop")
    for _ in range(3):
        store.save_event(
            TrackingEvent(
                requester=news,
                tracker_domains=["ads.example", "pixel.example"],
                fingerprinting=True,
            )
        )
    store.save_event(TrackingEvent(requester=shop, tracker_domains=["ads.example"]))
    for _ in range(4):
        store.save_event(
            PermissionRequestEvent(
                requester=Requester(kind="application", bundle_id="com.cam", display_name="Cam"),
                permission="camera",
                state="granted",
            )
        )
    checked = FileUploadEvent(requester=shop, file_count=2)
    abandoned = FileUploadEvent(requester=shop)
    for upload in (checked, abandoned):
        store.save_event(upload)
    _decide(store, checked.id, Outcome.INTERVENE)
    store.mark_aborted(abandoned.id)
    banner = ConsentBannerEvent(requester=news, cmp="onetrust")
    store.save_event(banner)
    store.save_event(ConsentBannerEvent(requester=news, cmp="onetrust"))
    _decide(store, banner.id, Outcome.INFORM, auto_action="reject_optional")
    store.save_response(UserResponse(event_id=banner.id, action="reject_optional"))
    # A second answer to the same event replaces the first; it is not a second decision.
    store.save_response(UserResponse(event_id=checked.id, action="continue"))
    store.save_response(UserResponse(event_id=checked.id, action="cancel"))
    store.cache_document(
        "https://news.example",
        "a" * 8,
        {"policy": {"missing": False}, "terms": {"missing": True}, "word_counts": {"policy": 2300}},
    )
    store.cache_document("https://shop.example", "b" * 8, {"policy": {"missing": True}})
    store.cache_document("https://old.example", "c" * 8, {"policy": {"missing": False}}, ttl_days=0)

    tally = store.tally()
    store.close()

    assert tally["since"]
    assert (tally["sites"], tally["apps"]) == (2, 1)
    assert tally["trackers"] == 3  # news→ads, news→pixel, shop→ads
    assert tally["tracker_networks"] == 2
    assert (tally["tracked_sites"], tally["fingerprinting_sites"]) == (2, 1)
    assert (tally["files"], tally["sensitive_files"]) == (2, 1)
    assert (tally["policies"], tally["terms"], tally["document_words"]) == (1, 0, 2300)
    assert (tally["banners"], tally["banner_sites"]) == (2, 1)
    assert (tally["grants"], tally["granted_apps"]) == (1, 1)
    assert tally["decided"] == {
        "reject_optional": {"count": 1, "automatic": 1},
        "cancel": {"count": 1, "automatic": 0},
    }


def test_tally_of_an_empty_store_is_all_zeros(tmp_path: Path) -> None:
    store = Store(tmp_path / "empty.sqlite3")
    tally = store.tally()
    store.close()
    assert tally["since"] == ""
    assert tally["decided"] == {}
    assert all(value == 0 for key, value in tally.items() if key not in {"since", "decided"})
