from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    EscalationStatus,
    EscalationView,
    EventEnvelope,
    SessionView,
    SkillStep,
)


class OperationalRepository:
    """Small durable store for active orchestration state and the cloud-write outbox."""

    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS participant_sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          role TEXT NOT NULL,
          participant_name TEXT NOT NULL,
          preferences_json TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS web_sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          participant_session_id TEXT NOT NULL,
          state TEXT NOT NULL,
          state_version INTEGER NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_web_sessions_user_updated
          ON web_sessions(user_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS event_ledger (
          event_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          page_instance_id TEXT NOT NULL,
          sequence_no INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          occurred_at TEXT NOT NULL,
          accepted_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_session_sequence
          ON event_ledger(session_id, page_instance_id, sequence_no);
        CREATE TABLE IF NOT EXISTS recorded_steps (
          session_id TEXT NOT NULL,
          step_no INTEGER NOT NULL,
          step_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY(session_id, step_no)
        );
        CREATE TABLE IF NOT EXISTS browser_sessions (
          web_session_id TEXT PRIMARY KEY,
          provider_session_id TEXT NOT NULL UNIQUE,
          start_url TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          attached_at TEXT,
          stopped_at TEXT,
          terminal_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS model_calls (
          call_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          step_id TEXT,
          guidance_mode TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          input_tokens INTEGER,
          output_tokens INTEGER,
          latency_ms INTEGER,
          status TEXT NOT NULL,
          rate_card_version TEXT,
          cost_usd TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS escalations (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          reason TEXT NOT NULL,
          status TEXT NOT NULL,
          caregiver_name TEXT,
          caregiver_note TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_escalation_once
          ON escalations(session_id, reason);
        CREATE TABLE IF NOT EXISTS telemetry_outbox (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          stable_key TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error_code TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(kind, stable_key)
        );
        CREATE TABLE IF NOT EXISTS cooldowns (
          user_id TEXT NOT NULL,
          page_key TEXT NOT NULL,
          dismissed_at TEXT NOT NULL,
          PRIMARY KEY(user_id, page_key)
        );
        CREATE TABLE IF NOT EXISTS activity_observations (
          activity_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          task_id TEXT NOT NULL,
          task_name TEXT NOT NULL,
          activity_type TEXT NOT NULL,
          origin TEXT,
          outcome TEXT,
          occurred_at TEXT NOT NULL,
          timezone TEXT NOT NULL,
          local_weekday INTEGER NOT NULL,
          local_minute INTEGER NOT NULL,
          details_json TEXT NOT NULL DEFAULT '{}',
          memory_sync_state TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE INDEX IF NOT EXISTS idx_activity_user_task_time
          ON activity_observations(user_id, task_id, activity_type, occurred_at);
        CREATE INDEX IF NOT EXISTS idx_activity_session_time
          ON activity_observations(session_id, occurred_at);
        CREATE TABLE IF NOT EXISTS reminder_actions (
          reminder_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          task_id TEXT NOT NULL,
          status TEXT NOT NULL,
          acted_at TEXT NOT NULL,
          snoozed_until TEXT,
          PRIMARY KEY(reminder_id, user_id)
        );
        """
        with self._lock, self._connection:
            self._connection.executescript(schema)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def create_participant(
        self,
        *,
        participant_id: UUID,
        user_id: str,
        role: str,
        participant_name: str,
        preferences: dict[str, Any],
        expires_at: datetime,
    ) -> None:
        now = self._now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO participant_sessions
                  (id, user_id, role, participant_name, preferences_json, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(participant_id),
                    user_id,
                    role,
                    participant_name,
                    json.dumps(preferences, separators=(",", ":")),
                    expires_at.isoformat(),
                    now,
                ),
            )

    def get_participant(self, participant_id: UUID | str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM participant_sessions WHERE id = ?", (str(participant_id),)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["preferences"] = json.loads(result.pop("preferences_json"))
        return result

    def record_activity(
        self,
        *,
        activity_id: str,
        user_id: str,
        session_id: UUID | str,
        task_id: str,
        task_name: str,
        activity_type: str,
        occurred_at: datetime,
        timezone: str,
        local_weekday: int,
        local_minute: int,
        origin: str | None = None,
        outcome: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO activity_observations
                  (activity_id, user_id, session_id, task_id, task_name, activity_type,
                   origin, outcome, occurred_at, timezone, local_weekday, local_minute,
                   details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    user_id,
                    str(session_id),
                    task_id,
                    task_name,
                    activity_type,
                    origin,
                    outcome,
                    occurred_at.isoformat(),
                    timezone,
                    local_weekday,
                    local_minute,
                    json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
                ),
            )
        return cursor.rowcount == 1

    def list_activities(
        self,
        user_id: str,
        *,
        activity_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        where = "WHERE user_id = ?"
        parameters: list[Any] = [user_id]
        if activity_type is not None:
            where += " AND activity_type = ?"
            parameters.append(activity_type)
        parameters.append(limit)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM activity_observations {where}
                ORDER BY occurred_at DESC LIMIT ?
                """,
                parameters,
            ).fetchall()
        rows = list(reversed(rows))
        activities: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            activities.append(item)
        return activities

    def summarize_session_activity(self, session_id: UUID | str) -> dict[str, Any] | None:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM activity_observations
                WHERE session_id = ? ORDER BY occurred_at ASC
                """,
                (str(session_id),),
            ).fetchall()
        if not rows:
            return None
        items = [dict(row) for row in rows]
        counts: dict[str, int] = {}
        origins: list[str] = []
        outcome: str | None = None
        for item in items:
            activity_type = str(item["activity_type"])
            counts[activity_type] = counts.get(activity_type, 0) + 1
            if item.get("origin") and item["origin"] not in origins:
                origins.append(str(item["origin"]))
            if item.get("outcome"):
                outcome = str(item["outcome"])
        first = items[0]
        return {
            "session_id": str(session_id),
            "user_id": first["user_id"],
            "task_id": first["task_id"],
            "task_name": first["task_name"],
            "started_at": first["occurred_at"],
            "ended_at": items[-1]["occurred_at"],
            "timezone": first["timezone"],
            "origins": origins,
            "activity_counts": counts,
            "outcome": outcome or "incomplete",
        }

    def mark_session_activity_synced(self, session_id: UUID | str, *, synced: bool) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE activity_observations SET memory_sync_state = ? WHERE session_id = ?
                """,
                ("synced" if synced else "failed", str(session_id)),
            )

    def record_reminder_action(
        self,
        *,
        reminder_id: str,
        user_id: str,
        task_id: str,
        status: str,
        acted_at: datetime,
        snoozed_until: datetime | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO reminder_actions
                  (reminder_id, user_id, task_id, status, acted_at, snoozed_until)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(reminder_id, user_id) DO UPDATE SET
                  status = excluded.status,
                  acted_at = excluded.acted_at,
                  snoozed_until = excluded.snoozed_until
                """,
                (
                    reminder_id,
                    user_id,
                    task_id,
                    status,
                    acted_at.isoformat(),
                    snoozed_until.isoformat() if snoozed_until else None,
                ),
            )

    def get_reminder_action(self, reminder_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM reminder_actions WHERE reminder_id = ? AND user_id = ?
                """,
                (reminder_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def create_session(self, session: SessionView) -> SessionView:
        payload = session.model_dump(mode="json")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO web_sessions
                  (id, user_id, participant_session_id, state, state_version, payload_json,
                   created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session.id),
                    session.user_id,
                    str(session.participant_session_id),
                    session.state.value,
                    session.state_version,
                    json.dumps(payload, separators=(",", ":")),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
        return session

    def get_session(self, session_id: UUID | str) -> SessionView | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM web_sessions WHERE id = ?", (str(session_id),)
            ).fetchone()
        return SessionView.model_validate_json(row[0]) if row else None

    def list_sessions(self, user_id: str, limit: int = 50) -> list[SessionView]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload_json FROM web_sessions
                WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [SessionView.model_validate_json(row[0]) for row in rows]

    def update_session(
        self,
        session_id: UUID | str,
        *,
        increment_version: bool = True,
        **changes: Any,
    ) -> SessionView:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT payload_json FROM web_sessions WHERE id = ?", (str(session_id),)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown session {session_id}")
            current = SessionView.model_validate_json(row[0])
            changes["updated_at"] = datetime.now(UTC)
            if increment_version:
                changes["state_version"] = current.state_version + 1
            updated = current.model_copy(update=changes)
            payload = updated.model_dump(mode="json")
            self._connection.execute(
                """
                UPDATE web_sessions
                SET state = ?, state_version = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.state.value,
                    updated.state_version,
                    json.dumps(payload, separators=(",", ":")),
                    updated.updated_at.isoformat(),
                    str(session_id),
                ),
            )
        return updated

    def append_event(self, event: EventEnvelope) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO event_ledger
                  (event_id, session_id, page_instance_id, sequence_no, event_type, payload_json,
                   occurred_at, accepted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.event_id),
                    str(event.session_id),
                    str(event.page_instance_id),
                    event.sequence_no,
                    event.event_type.value,
                    event.model_dump_json(),
                    event.occurred_at.isoformat(),
                    self._now(),
                ),
            )
        return cursor.rowcount == 1

    def highest_sequence(self, session_id: UUID | str, page_instance_id: UUID | str) -> int:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COALESCE(MAX(sequence_no), -1) FROM event_ledger
                WHERE session_id = ? AND page_instance_id = ?
                """,
                (str(session_id), str(page_instance_id)),
            ).fetchone()
        return int(row[0])

    def record_step(self, session_id: UUID | str, step: SkillStep) -> int:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(step_no), 0) + 1 FROM recorded_steps WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            step_no = int(row[0])
            self._connection.execute(
                """
                INSERT INTO recorded_steps(session_id, step_no, step_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(session_id), step_no, step.model_dump_json(), self._now()),
            )
        return step_no

    def get_recorded_steps(self, session_id: UUID | str) -> list[SkillStep]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT step_json FROM recorded_steps WHERE session_id = ? ORDER BY step_no
                """,
                (str(session_id),),
            ).fetchall()
        return [SkillStep.model_validate_json(row[0]) for row in rows]

    def save_browser_session(
        self,
        *,
        web_session_id: UUID | str,
        provider_session_id: str,
        start_url: str,
        status: str,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO browser_sessions
                  (web_session_id, provider_session_id, start_url, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(web_session_id) DO UPDATE SET
                  provider_session_id = excluded.provider_session_id,
                  start_url = excluded.start_url,
                  status = excluded.status
                """,
                (str(web_session_id), provider_session_id, start_url, status, self._now()),
            )

    def update_browser_session(
        self, web_session_id: UUID | str, *, status: str, terminal_reason: str | None = None
    ) -> None:
        now = self._now()
        attached_at = now if status == "connected" else None
        stopped_at = now if status in {"stopped", "termination_failed"} else None
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE browser_sessions SET status = ?,
                  attached_at = COALESCE(?, attached_at),
                  stopped_at = COALESCE(?, stopped_at),
                  terminal_reason = COALESCE(?, terminal_reason)
                WHERE web_session_id = ?
                """,
                (status, attached_at, stopped_at, terminal_reason, str(web_session_id)),
            )

    def get_browser_session(self, web_session_id: UUID | str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM browser_sessions WHERE web_session_id = ?",
                (str(web_session_id),),
            ).fetchone()
        return dict(row) if row else None

    def save_model_call(self, values: dict[str, Any]) -> None:
        keys = [
            "call_id",
            "session_id",
            "step_id",
            "guidance_mode",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "status",
            "rate_card_version",
            "cost_usd",
        ]
        row = [values.get(key) for key in keys]
        with self._lock, self._connection:
            self._connection.execute(
                f"INSERT OR IGNORE INTO model_calls ({', '.join(keys)}, created_at) "
                f"VALUES ({', '.join('?' for _ in keys)}, ?)",
                (*row, self._now()),
            )

    def create_escalation(
        self, session_id: UUID | str, user_id: str, reason: str
    ) -> EscalationView:
        now = datetime.now(UTC)
        escalation_id = uuid4()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO escalations
                  (id, session_id, user_id, reason, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(escalation_id),
                    str(session_id),
                    user_id,
                    reason,
                    EscalationStatus.PENDING.value,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM escalations WHERE session_id = ? AND reason = ?",
                (str(session_id), reason),
            ).fetchone()
        return EscalationView.model_validate(dict(row))

    def list_escalations(self, user_id: str) -> list[EscalationView]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM escalations WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [EscalationView.model_validate(dict(row)) for row in rows]

    def update_escalation_note(
        self, escalation_id: UUID | str, author_name: str, text: str
    ) -> EscalationView:
        now = self._now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE escalations SET caregiver_name = ?, caregiver_note = ?,
                  status = ?, updated_at = ? WHERE id = ?
                """,
                (author_name, text, EscalationStatus.ACKNOWLEDGED.value, now, str(escalation_id)),
            )
            row = self._connection.execute(
                "SELECT * FROM escalations WHERE id = ?", (str(escalation_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown escalation {escalation_id}")
        return EscalationView.model_validate(dict(row))

    def set_cooldown(self, user_id: str, page_key: str, dismissed_at: datetime) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO cooldowns(user_id, page_key, dismissed_at) VALUES (?, ?, ?)
                ON CONFLICT(user_id, page_key) DO UPDATE SET dismissed_at = excluded.dismissed_at
                """,
                (user_id, page_key, dismissed_at.isoformat()),
            )

    def get_cooldown(self, user_id: str, page_key: str) -> datetime | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT dismissed_at FROM cooldowns WHERE user_id = ? AND page_key = ?",
                (user_id, page_key),
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def enqueue(self, kind: str, stable_key: str, payload: dict[str, Any]) -> None:
        now = self._now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO telemetry_outbox
                  (id, kind, stable_key, payload_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    str(uuid4()),
                    kind,
                    stable_key,
                    json.dumps(payload, separators=(",", ":"), default=str),
                    now,
                    now,
                ),
            )

    def pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM telemetry_outbox WHERE status IN ('pending', 'failed')
                ORDER BY created_at LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def mark_outbox(self, item_id: str, *, synced: bool, error_code: str | None = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE telemetry_outbox SET status = ?, attempts = attempts + 1,
                  last_error_code = ?, updated_at = ? WHERE id = ?
                """,
                ("synced" if synced else "failed", error_code, self._now(), item_id),
            )
