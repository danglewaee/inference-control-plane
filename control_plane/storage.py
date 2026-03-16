from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistenceStore:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def initialize(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS backend_registry (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rollout_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS request_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decision_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    backend TEXT,
                    payload TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save_backends(self, backends: list[dict[str, Any]]) -> None:
        timestamp = utcnow()
        with self._lock:
            self._conn.execute("DELETE FROM backend_registry")
            self._conn.executemany(
                "INSERT INTO backend_registry (name, payload, updated_at) VALUES (?, ?, ?)",
                [(backend["name"], json.dumps(backend), timestamp) for backend in backends],
            )
            self._conn.commit()

    def load_backends(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM backend_registry ORDER BY name ASC").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_rollout_state(self, rollout_state: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO rollout_state (id, payload, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (json.dumps(rollout_state), utcnow()),
            )
            self._conn.commit()

    def load_rollout_state(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM rollout_state WHERE id = 1").fetchone()
        return None if row is None else json.loads(row["payload"])

    def append_request_history(self, payload: dict[str, Any]) -> None:
        created_at = payload.get("created_at", utcnow())
        with self._lock:
            self._conn.execute(
                "INSERT INTO request_history (created_at, request_id, payload) VALUES (?, ?, ?)",
                (created_at, payload["request_id"], json.dumps(payload)),
            )
            self._conn.commit()

    def append_decision_log(self, *, request_id: str, event_type: str, backend: str | None, detail: dict[str, Any]) -> None:
        payload = {
            "created_at": utcnow(),
            "request_id": request_id,
            "event_type": event_type,
            "backend": backend,
            "detail": detail,
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO decision_logs (created_at, request_id, event_type, backend, payload) VALUES (?, ?, ?, ?, ?)",
                (payload["created_at"], request_id, event_type, backend, json.dumps(payload)),
            )
            self._conn.commit()

    def list_request_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM request_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def list_decision_logs(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM decision_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def clear_events(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM request_history")
            self._conn.execute("DELETE FROM decision_logs")
            self._conn.commit()
