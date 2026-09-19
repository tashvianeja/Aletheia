from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from privacy_guardian.core.events import Decision, PrivacyEvent, UserResponse
from privacy_guardian.util.privacy import safe_origin, sanitize


class Store:
    SCHEMA_VERSION = 2

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.path.chmod(0o600)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        with self._lock, self.connection:
            if self.connection.execute("PRAGMA user_version").fetchone()[0] > self.SCHEMA_VERSION:
                raise ValueError("Database was created by a newer Privacy Guardian version")
            self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,ts TEXT NOT NULL,event_type TEXT NOT NULL,requester TEXT NOT NULL,categories TEXT NOT NULL,event_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,ts TEXT NOT NULL,outcome TEXT NOT NULL,risk REAL NOT NULL,decision_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS user_responses(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,ts TEXT NOT NULL,action TEXT NOT NULL,response_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS site_profiles(key TEXT PRIMARY KEY,updated_at TEXT NOT NULL,profile_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS app_profiles(key TEXT PRIMARY KEY,updated_at TEXT NOT NULL,profile_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS learned_rules(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS document_cache(origin TEXT NOT NULL,digest TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,profile_json TEXT NOT NULL,PRIMARY KEY(origin,digest));
            """)
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(events)")}
            if "status" not in columns:
                self.connection.execute(
                    "ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'"
                )
            self.connection.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS events_requester ON events(requester)"
            )
            self.connection.execute("DELETE FROM schema_version")
            self.connection.execute("INSERT INTO schema_version VALUES (?)", (self.SCHEMA_VERSION,))
            self.connection.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(sanitize(value), separators=(",", ":"), ensure_ascii=False)

    def save_event(self, event: PrivacyEvent) -> None:
        value = event.model_dump(mode="json")
        value.pop("payload_ref", None)
        value.pop("fields", None)
        value["requester"]["origin"] = safe_origin(event.requester.origin)
        # Paths and app names can contain user identities; store public identity only.
        value["requester"].pop("exe_path", None)
        identity = (
            safe_origin(event.requester.key)
            if event.requester.origin
            else event.requester.bundle_id
            or "app:" + hashlib.sha256(event.requester.exe_path.lower().encode()).hexdigest()[:24]
        )
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO events(id,ts,event_type,requester,categories,event_json,status) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ts=excluded.ts,event_type=excluded.event_type,requester=excluded.requester,categories=excluded.categories,event_json=excluded.event_json",
                (
                    event.id,
                    event.ts.isoformat(),
                    event.event_type,
                    identity,
                    self._json(event.data_categories),
                    self._json(value),
                    "complete",
                ),
            )

    def save_decision(self, decision: Decision) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO decisions(event_id,ts,outcome,risk,decision_json) VALUES (?,?,?,?,?)",
                (
                    decision.event_id,
                    datetime.now(UTC).isoformat(),
                    decision.outcome,
                    decision.risk,
                    self._json(decision.model_dump(mode="json")),
                ),
            )

    def save_response(self, response: UserResponse) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO user_responses(event_id,ts,action,response_json) VALUES (?,?,?,?)",
                (
                    response.event_id,
                    response.ts.isoformat(),
                    response.action,
                    self._json(response.model_dump(mode="json")),
                ),
            )

    def mark_aborted(self, event_id: str) -> None:
        with self._lock, self.connection:
            self.connection.execute("UPDATE events SET status='aborted' WHERE id=?", (event_id,))

    def history(
        self, limit: int = 100, requester: str | None = None, outcome: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT e.*,d.decision_json FROM events e LEFT JOIN decisions d ON d.id=(SELECT MAX(id) FROM decisions WHERE event_id=e.id) WHERE 1=1"
        args: list[Any] = []
        if requester:
            sql += " AND e.requester=?"
            args.append(safe_origin(requester))
        if outcome:
            sql += " AND d.outcome=?"
            args.append(outcome)
        args.append(min(max(limit, 1), 10000))
        with self._lock:
            rows = self.connection.execute(sql + " ORDER BY e.ts DESC LIMIT ?", args).fetchall()
        return [
            {
                "event": json.loads(row["event_json"]),
                "decision": json.loads(row["decision_json"]) if row["decision_json"] else None,
                "status": row["status"],
            }
            for row in rows
        ]

    def set_preference(self, key: str, value: Any) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO preferences VALUES (?,?,?)",
                (key, self._json(value), datetime.now(UTC).isoformat()),
            )

    def get_preferences(self) -> dict[str, Any]:
        with self._lock:
            return {
                row[0]: json.loads(row[1])
                for row in self.connection.execute("SELECT key,value_json FROM preferences")
            }

    def set_learned_rule(self, key: str, value: Any) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO learned_rules VALUES (?,?,?)",
                (key, self._json(value), datetime.now(UTC).isoformat()),
            )

    def get_learned_rules(self) -> dict[str, Any]:
        with self._lock:
            return {
                row[0]: json.loads(row[1])
                for row in self.connection.execute("SELECT key,value_json FROM learned_rules")
            }

    def put_profile(self, kind: str, key: str, profile: dict[str, Any]) -> None:
        table = "site_profiles" if kind in {"site", "website"} else "app_profiles"
        with self._lock, self.connection:
            self.connection.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?,?,?)",
                (safe_origin(key), datetime.now(UTC).isoformat(), self._json(profile)),
            )

    def get_profile(self, kind: str, key: str) -> dict[str, Any] | None:
        table = "site_profiles" if kind in {"site", "website"} else "app_profiles"
        with self._lock:
            row = self.connection.execute(
                f"SELECT profile_json FROM {table} WHERE key=?", (safe_origin(key),)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def cache_document(
        self, origin: str, digest: str, profile: dict[str, Any], ttl_days: int = 30
    ) -> None:
        now = datetime.now(UTC)
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO document_cache VALUES (?,?,?,?,?)",
                (
                    safe_origin(origin),
                    digest,
                    now.isoformat(),
                    (now + timedelta(days=ttl_days)).isoformat(),
                    self._json(profile),
                ),
            )

    def get_cached_document(self, origin: str, digest: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT profile_json FROM document_cache WHERE origin=? AND digest=? AND expires_at>?",
                (safe_origin(origin), digest, datetime.now(UTC).isoformat()),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def purge(self, days: int = 90) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self._lock, self.connection:
            count = self.connection.execute("DELETE FROM events WHERE ts<?", (cutoff,)).rowcount
            self.connection.execute(
                "DELETE FROM document_cache WHERE expires_at<?", (datetime.now(UTC).isoformat(),)
            )
        return count

    def export_preferences(self) -> dict[str, Any]:
        return {
            "version": 1,
            "preferences": self.get_preferences(),
            "learned_rules": self.get_learned_rules(),
        }

    def import_preferences(self, payload: dict[str, Any]) -> None:
        if payload.get("version") != 1 or not isinstance(payload.get("preferences"), dict):
            raise ValueError("Unsupported preferences format")
        for key, value in payload["preferences"].items():
            self.set_preference(key, value)
        for key, value in payload.get("learned_rules", {}).items():
            self.set_learned_rule(key, value)

    def diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {
                table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "events",
                    "decisions",
                    "user_responses",
                    "site_profiles",
                    "app_profiles",
                    "preferences",
                    "learned_rules",
                    "document_cache",
                )
            }

    def close(self) -> None:
        with self._lock:
            self.connection.close()
