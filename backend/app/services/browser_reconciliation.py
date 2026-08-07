"""Browserbase lifecycle reconciliation.

Compares WebAccessible-owned Browserbase sessions against the operational SQLite
record of active browser sessions and releases only the provider sessions that are
clearly orphaned or expired.

Prohibitions enforced by construction in this module:

- No Browserbase Agent API is imported, referenced, or called.
- No CDP attachment happens; nothing here clicks, types, navigates, or reads page
  content. The only provider verbs used are list, retrieve-status, and terminate.
- No provider outcome is ever assumed. A session is reported terminated only when
  the provider itself reports a terminal status (or reports that it is gone).
- Dry run is the default. Nothing is terminated and no local row is written unless
  the caller explicitly asks to execute.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from backend.app.integrations.browserbase.client import (
    AGENT_SURFACE_METADATA_KEY,
    ENVIRONMENT_METADATA_KEY,
    LIVE_SESSION_STATUSES,
    OWNER_METADATA_KEY,
    TERMINAL_SESSION_STATUSES,
    BrowserbaseProviderError,
    SessionRecord,
    SessionStatus,
    TerminationResult,
)

__all__ = [
    "BrowserReconciliationService",
    "Disposition",
    "LocalBrowserSession",
    "LocalSessionStore",
    "LocalStateUnavailableError",
    "Outcome",
    "Reason",
    "ReconciliationPolicy",
    "ReconciliationProvider",
    "ReconciliationReport",
    "SessionOutcome",
    "SqliteLocalSessionStore",
    "policy_from_settings",
    "sanitize",
]

SCHEMA_VERSION = "webaccessible.browserbase-reconciliation/1"

#: Provider statuses that still hold a managed browser slot, queried one at a time
#: because the provider list endpoint accepts a single status.
LIVE_QUERY_STATUSES: tuple[SessionStatus, ...] = ("RUNNING", "PENDING")

#: Operational statuses meaning the backend has already given up the provider session.
LOCAL_RELEASED_STATUSES = frozenset({"stopped", "termination_failed"})

_LOCAL_TABLE = "browser_sessions"


class Disposition(StrEnum):
    ACTIVE = "active"
    ORPHANED = "orphaned"
    SKIPPED = "skipped"


class Reason(StrEnum):
    # Active
    LEASE_HELD = "lease_held"
    RECLAIMED_BY_BACKEND = "reclaimed_by_backend"
    # Orphaned
    UNKNOWN_LOCAL_SESSION = "unknown_local_session"
    LOCAL_SESSION_RELEASED = "local_session_released"
    PROVIDER_SESSION_SUPERSEDED = "provider_session_superseded"
    PROVIDER_EXPIRY_PASSED = "provider_expiry_passed"
    LEASE_EXPIRED = "lease_expired"
    # Skipped
    NOT_WEBACCESSIBLE_OWNED = "not_webaccessible_owned"
    FOREIGN_ENVIRONMENT = "foreign_environment"
    AGENT_SURFACE_FLAGGED = "agent_surface_flagged"
    PROVIDER_ALREADY_TERMINAL = "provider_already_terminal"
    WITHIN_STARTUP_GRACE = "within_startup_grace"


class Outcome(StrEnum):
    NONE = "none"
    DRY_RUN = "dry_run"
    TERMINATED = "terminated"
    ALREADY_TERMINAL = "already_terminal"
    FAILED = "failed"
    DEFERRED_TERMINATION_LIMIT = "deferred_termination_limit"


class LocalStateUnavailableError(RuntimeError):
    """The operational store could not be read, so ownership cannot be judged."""


@dataclass(frozen=True, slots=True)
class ReconciliationPolicy:
    """Bounds that decide what may be released and how much may be released at once."""

    environment: str
    #: Longest a WebAccessible session may hold a provider session, mirroring
    #: ``browserbase_session_timeout_seconds``.
    lease_ttl_seconds: float
    #: Slack added to the lease before an otherwise-active session is judged expired.
    lease_grace_seconds: float = 120.0
    #: Minimum provider session age before it may be judged orphaned at all. Covers
    #: the window between provider create and the operational row being written.
    startup_grace_seconds: float = 180.0
    #: Hard blast-radius bound for one pass.
    max_terminations: int = 25
    #: Require the owner metadata environment to match ``environment``.
    match_environment: bool = True

    def __post_init__(self) -> None:
        if not self.environment.strip():
            raise ValueError("environment must not be blank")
        if self.lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        if self.lease_grace_seconds < 0:
            raise ValueError("lease_grace_seconds must not be negative")
        if self.startup_grace_seconds < 0:
            raise ValueError("startup_grace_seconds must not be negative")
        if self.max_terminations < 0:
            raise ValueError("max_terminations must not be negative")

    @property
    def owner_environment(self) -> str | None:
        """Metadata environment used to narrow the provider list query."""

        return self.environment if self.match_environment else None


@dataclass(frozen=True, slots=True)
class LocalBrowserSession:
    """One operational ``browser_sessions`` row."""

    web_session_id: str
    provider_session_id: str
    status: str
    created_at: datetime | None
    attached_at: datetime | None
    stopped_at: datetime | None

    @property
    def released(self) -> bool:
        return self.status in LOCAL_RELEASED_STATUSES


class LocalSessionStore(Protocol):
    """Read model of operational browser-session state, with optional write-back."""

    @property
    def writable(self) -> bool: ...

    def snapshot(self) -> Mapping[str, LocalBrowserSession]:
        """Return live-or-released rows keyed by canonical WebAccessible session ID."""
        ...

    def record_release(self, provider_session_id: str, *, reason: str) -> bool:
        """Idempotently mark a provider-confirmed release. Returns whether a row changed."""
        ...


class ReconciliationProvider(Protocol):
    """The read/terminate slice of the Browserbase provider used here."""

    async def list_sessions(
        self,
        *,
        status: SessionStatus | None = None,
        owner_environment: str | None = None,
    ) -> Sequence[SessionRecord]: ...

    async def terminate(self, session_id: str) -> TerminationResult: ...


class SqliteLocalSessionStore:
    """Reads ``browser_sessions`` from the operational SQLite database.

    Opens its own short-lived connections so it never shares transaction state with
    a running backend. Read-only unless ``writable`` is set, which the service only
    does in execute mode.
    """

    __slots__ = ("_path", "_timeout", "_writable")

    def __init__(
        self,
        database_path: str | Path,
        *,
        writable: bool = False,
        timeout: float = 5.0,
    ) -> None:
        path = Path(database_path)
        if not path.is_file():
            raise LocalStateUnavailableError(
                "The operational database was not found; refusing to judge provider "
                "sessions without local state."
            )
        self._path = path
        self._writable = writable
        self._timeout = timeout

    @property
    def writable(self) -> bool:
        return self._writable

    @property
    def database_path(self) -> Path:
        return self._path

    def snapshot(self) -> Mapping[str, LocalBrowserSession]:
        with self._connect(read_only=True) as connection:
            self._require_table(connection)
            rows = connection.execute(
                f"""
                SELECT web_session_id, provider_session_id, status,
                       created_at, attached_at, stopped_at
                FROM {_LOCAL_TABLE}
                """
            ).fetchall()
        sessions: dict[str, LocalBrowserSession] = {}
        for row in rows:
            provider_session_id = str(row["provider_session_id"] or "").strip()
            web_session_id = _canonical_id(str(row["web_session_id"] or ""))
            if not provider_session_id or not web_session_id:
                continue
            sessions[web_session_id] = LocalBrowserSession(
                web_session_id=web_session_id,
                provider_session_id=provider_session_id,
                status=str(row["status"] or "").strip().casefold(),
                created_at=_parse_timestamp(row["created_at"]),
                attached_at=_parse_timestamp(row["attached_at"]),
                stopped_at=_parse_timestamp(row["stopped_at"]),
            )
        return sessions

    def record_release(self, provider_session_id: str, *, reason: str) -> bool:
        if not self._writable:
            return False
        now = datetime.now(UTC).isoformat()
        with self._connect(read_only=False) as connection:
            self._require_table(connection)
            with connection:
                cursor = connection.execute(
                    f"""
                    UPDATE {_LOCAL_TABLE}
                    SET status = 'stopped',
                        stopped_at = COALESCE(stopped_at, ?),
                        terminal_reason = COALESCE(terminal_reason, ?)
                    WHERE provider_session_id = ? AND status <> 'stopped'
                    """,
                    (now, reason, provider_session_id),
                )
        return cursor.rowcount > 0

    @contextmanager
    def _connect(self, *, read_only: bool) -> Iterator[sqlite3.Connection]:
        if read_only:
            uri = f"file:{self._path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=self._timeout)
        else:
            connection = sqlite3.connect(self._path, timeout=self._timeout)
        connection.row_factory = sqlite3.Row
        with closing(connection):
            connection.execute(f"PRAGMA busy_timeout = {int(self._timeout * 1000)}")
            yield connection

    @staticmethod
    def _require_table(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (_LOCAL_TABLE,),
        ).fetchone()
        if row is None:
            raise LocalStateUnavailableError(
                f"The operational database has no {_LOCAL_TABLE} table; refusing to "
                "judge provider sessions without local state."
            )


@dataclass(slots=True)
class SessionOutcome:
    """Per-session reconciliation result. Carries no URL, key, or page content."""

    provider_session_id: str
    provider_status: str
    region: str
    owned: bool
    web_session_id: str | None
    disposition: Disposition
    reason: Reason
    age_seconds: float | None
    expires_in_seconds: float | None
    local_status: str | None = None
    outcome: Outcome = Outcome.NONE
    provider_confirmed: bool = False
    local_state_updated: bool = False
    error_code: str | None = None
    retryable: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_session_id": self.provider_session_id,
            "provider_status": self.provider_status,
            "region": self.region,
            "owned": self.owned,
            "web_session_id": self.web_session_id,
            "disposition": self.disposition.value,
            "reason": self.reason.value,
            "age_seconds": _round(self.age_seconds),
            "expires_in_seconds": _round(self.expires_in_seconds),
            "local_status": self.local_status,
            "outcome": self.outcome.value,
            "provider_confirmed": self.provider_confirmed,
            "local_state_updated": self.local_state_updated,
            "error_code": self.error_code,
            "retryable": self.retryable,
        }


@dataclass(slots=True)
class ReconciliationReport:
    """Sanitized structured result of one reconciliation pass."""

    mode: str
    environment: str
    started_at: datetime
    finished_at: datetime
    local_session_count: int
    sessions: list[SessionOutcome] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    provider_error: dict[str, Any] | None = None
    local_state_writable: bool = False

    @property
    def counts(self) -> dict[str, int]:
        outcomes = [record.outcome for record in self.sessions]
        dispositions = [record.disposition for record in self.sessions]
        terminated = sum(
            1 for outcome in outcomes if outcome in {Outcome.TERMINATED, Outcome.ALREADY_TERMINAL}
        )
        return {
            "inspected": len(self.sessions),
            "owned": sum(1 for record in self.sessions if record.owned),
            "active": sum(1 for value in dispositions if value is Disposition.ACTIVE),
            "orphaned": sum(1 for value in dispositions if value is Disposition.ORPHANED),
            "terminated": terminated,
            "already_terminal": sum(1 for value in outcomes if value is Outcome.ALREADY_TERMINAL),
            "failed": sum(1 for value in outcomes if value is Outcome.FAILED),
            "skipped": sum(1 for value in dispositions if value is Disposition.SKIPPED),
            "deferred": sum(1 for value in outcomes if value is Outcome.DEFERRED_TERMINATION_LIMIT),
        }

    @property
    def ok(self) -> bool:
        return self.provider_error is None and self.counts["failed"] == 0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "environment": self.environment,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_ms": int((self.finished_at - self.started_at).total_seconds() * 1000),
            "ok": self.ok,
            "provider_error": self.provider_error,
            "local_session_count": self.local_session_count,
            "local_state_writable": self.local_state_writable,
            "counts": self.counts,
            "anomalies": list(self.anomalies),
            "sessions": [record.to_dict() for record in self.sessions],
        }
        sanitized = sanitize(payload)
        assert isinstance(sanitized, dict)
        return sanitized


class BrowserReconciliationService:
    """Reconciles WebAccessible-owned Browserbase sessions against operational state."""

    __slots__ = ("_local", "_policy", "_provider")

    def __init__(
        self,
        *,
        provider: ReconciliationProvider,
        local_state: LocalSessionStore,
        policy: ReconciliationPolicy,
    ) -> None:
        self._provider = provider
        self._local = local_state
        self._policy = policy

    @property
    def policy(self) -> ReconciliationPolicy:
        return self._policy

    async def reconcile(self, *, execute: bool = False) -> ReconciliationReport:
        """Inspect owned provider sessions and, when asked, release orphaned ones."""

        started = _now()
        mode = "execute" if execute else "dry_run"

        try:
            provider_sessions = await self._list_live_sessions()
        except BrowserbaseProviderError as error:
            return ReconciliationReport(
                mode=mode,
                environment=self._policy.environment,
                started_at=started,
                finished_at=_now(),
                local_session_count=0,
                provider_error={
                    "code": error.code.value,
                    "retryable": error.retryable,
                    "status_code": error.status_code,
                },
                local_state_writable=self._local.writable,
            )

        # Read local state after the provider list so the snapshot is never older
        # than the sessions it is judging.
        local = self._local.snapshot()
        classified_at = _now()
        records = [self._classify(session, local, classified_at) for session in provider_sessions]

        report = ReconciliationReport(
            mode=mode,
            environment=self._policy.environment,
            started_at=started,
            finished_at=started,
            local_session_count=len(local),
            sessions=records,
            anomalies=_anomalies(records),
            local_state_writable=self._local.writable,
        )

        orphans = [record for record in records if record.disposition is Disposition.ORPHANED]
        if not execute:
            for record in orphans:
                record.outcome = Outcome.DRY_RUN
            report.finished_at = _now()
            return report

        await self._release(orphans, provider_sessions)
        report.anomalies = _anomalies(records)
        report.finished_at = _now()
        return report

    async def _list_live_sessions(self) -> tuple[SessionRecord, ...]:
        found: dict[str, SessionRecord] = {}
        for status in LIVE_QUERY_STATUSES:
            listed = await self._provider.list_sessions(
                status=status,
                owner_environment=self._policy.owner_environment,
            )
            for record in listed:
                found.setdefault(record.id, record)
        return tuple(found.values())

    async def _release(
        self,
        orphans: Sequence[SessionOutcome],
        provider_sessions: Sequence[SessionRecord],
    ) -> None:
        if not orphans:
            return

        # Re-read operational state immediately before mutating anything: the backend
        # may have claimed or replaced a session since the first snapshot.
        confirmed = self._local.snapshot()
        confirmed_at = _now()
        by_id = {session.id: session for session in provider_sessions}
        budget = self._policy.max_terminations

        for record in orphans:
            source = by_id.get(record.provider_session_id)
            if source is not None:
                recheck = self._classify(source, confirmed, confirmed_at)
                if recheck.disposition is not Disposition.ORPHANED:
                    record.disposition = Disposition.ACTIVE
                    record.reason = Reason.RECLAIMED_BY_BACKEND
                    record.local_status = recheck.local_status
                    record.outcome = Outcome.NONE
                    continue

            if budget <= 0:
                record.outcome = Outcome.DEFERRED_TERMINATION_LIMIT
                continue
            budget -= 1
            await self._terminate(record)

    async def _terminate(self, record: SessionOutcome) -> None:
        try:
            result = await self._provider.terminate(record.provider_session_id)
        except BrowserbaseProviderError as error:
            if error.status_code == 404:
                # The provider itself reports the session no longer exists, which is
                # the terminal state this pass wanted. Not a simulated success.
                record.outcome = Outcome.ALREADY_TERMINAL
                record.provider_status = "GONE"
                record.provider_confirmed = True
            else:
                record.outcome = Outcome.FAILED
                record.error_code = error.code.value
                record.retryable = error.retryable
                return
        else:
            record.provider_status = result.status
            record.provider_confirmed = result.status in TERMINAL_SESSION_STATUSES
            if not record.provider_confirmed:
                record.outcome = Outcome.FAILED
                record.error_code = "termination_unconfirmed"
                record.retryable = True
                return
            record.outcome = (
                Outcome.ALREADY_TERMINAL if result.already_terminal else Outcome.TERMINATED
            )

        if record.web_session_id is not None:
            try:
                record.local_state_updated = self._local.record_release(
                    record.provider_session_id,
                    reason=f"reconciled:{record.reason.value}",
                )
            except (sqlite3.Error, LocalStateUnavailableError):
                record.local_state_updated = False

    def _classify(
        self,
        session: SessionRecord,
        local: Mapping[str, LocalBrowserSession],
        now: datetime,
    ) -> SessionOutcome:
        metadata = session.user_metadata
        owner_id = _owner_session_id(metadata)
        created_at = _as_utc(session.created_at)
        expires_at = _as_utc(session.expires_at)
        age = (now - created_at).total_seconds() if created_at else None
        expires_in = (expires_at - now).total_seconds() if expires_at else None

        def build(
            disposition: Disposition,
            reason: Reason,
            *,
            owned: bool,
            local_status: str | None = None,
        ) -> SessionOutcome:
            return SessionOutcome(
                provider_session_id=session.id,
                provider_status=session.status,
                region=session.region,
                owned=owned,
                web_session_id=owner_id,
                disposition=disposition,
                reason=reason,
                age_seconds=age,
                expires_in_seconds=expires_in,
                local_status=local_status,
            )

        # Anything not holding a live browser slot is out of scope, terminal or not.
        if session.status not in LIVE_SESSION_STATUSES:
            return build(
                Disposition.SKIPPED, Reason.PROVIDER_ALREADY_TERMINAL, owned=owner_id is not None
            )
        if owner_id is None:
            return build(Disposition.SKIPPED, Reason.NOT_WEBACCESSIBLE_OWNED, owned=False)
        if _agent_surface_used(metadata):
            return build(Disposition.SKIPPED, Reason.AGENT_SURFACE_FLAGGED, owned=False)
        if self._policy.match_environment and not _environment_matches(
            metadata, self._policy.environment
        ):
            return build(Disposition.SKIPPED, Reason.FOREIGN_ENVIRONMENT, owned=False)

        # Past the provider deadline: releasing costs nothing the session still has.
        if expires_in is not None and expires_in <= 0:
            return build(Disposition.ORPHANED, Reason.PROVIDER_EXPIRY_PASSED, owned=True)

        if age is not None and age < self._policy.startup_grace_seconds:
            return build(Disposition.SKIPPED, Reason.WITHIN_STARTUP_GRACE, owned=True)

        row = local.get(owner_id)
        if row is None:
            return build(Disposition.ORPHANED, Reason.UNKNOWN_LOCAL_SESSION, owned=True)
        if row.provider_session_id != session.id:
            return build(
                Disposition.ORPHANED,
                Reason.PROVIDER_SESSION_SUPERSEDED,
                owned=True,
                local_status=row.status,
            )
        if row.released:
            return build(
                Disposition.ORPHANED,
                Reason.LOCAL_SESSION_RELEASED,
                owned=True,
                local_status=row.status,
            )

        lease_limit = self._policy.lease_ttl_seconds + self._policy.lease_grace_seconds
        lease_started = row.attached_at or row.created_at or created_at
        lease_age = (now - lease_started).total_seconds() if lease_started else age
        if lease_age is not None and lease_age > lease_limit:
            return build(
                Disposition.ORPHANED, Reason.LEASE_EXPIRED, owned=True, local_status=row.status
            )

        return build(Disposition.ACTIVE, Reason.LEASE_HELD, owned=True, local_status=row.status)


def _anomalies(records: Sequence[SessionOutcome]) -> list[dict[str, Any]]:
    """Conditions an operator must see, independent of the counts."""

    anomalies: list[dict[str, Any]] = []
    for record in records:
        if record.reason is Reason.AGENT_SURFACE_FLAGGED:
            anomalies.append(
                {
                    "kind": "agent_surface_metadata_present",
                    "provider_session_id": record.provider_session_id,
                    "severity": "critical",
                }
            )
        if record.outcome is Outcome.FAILED:
            anomalies.append(
                {
                    "kind": "termination_failed",
                    "provider_session_id": record.provider_session_id,
                    "error_code": record.error_code,
                    "severity": "high",
                }
            )
        if record.outcome is Outcome.DEFERRED_TERMINATION_LIMIT:
            anomalies.append(
                {
                    "kind": "termination_limit_reached",
                    "provider_session_id": record.provider_session_id,
                    "severity": "medium",
                }
            )
    return anomalies


_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "cdp",
    "connect",
    "cookie",
    "credential",
    "debugger",
    "live_view",
    "liveview",
    "password",
    "secret",
    "signing",
    "token",
    "url",
)

_SENSITIVE_VALUE = re.compile(r"(wss?://|https?://|bb_(live|test)_|\bBearer\s)", re.IGNORECASE)

REDACTED = "[redacted]"


def sanitize(payload: Any) -> Any:
    """Drop anything that looks like a credential, endpoint, or Live View surface.

    Nothing in a report should match these patterns; this is the last line of
    defence before a report reaches a log, stdout, or a reviewer.
    """

    if isinstance(payload, Mapping):
        clean: dict[str, Any] = {}
        for key, value in payload.items():
            name = str(key)
            lowered = name.casefold()
            if any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS):
                clean[name] = REDACTED
            else:
                clean[name] = sanitize(value)
        return clean
    if isinstance(payload, (list, tuple)):
        return [sanitize(item) for item in payload]
    if isinstance(payload, str):
        return REDACTED if _SENSITIVE_VALUE.search(payload) else payload
    return payload


def _owner_session_id(metadata: Mapping[str, Any]) -> str | None:
    """Return the canonical WebAccessible session ID this provider session claims."""

    raw = metadata.get(OWNER_METADATA_KEY)
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _agent_surface_used(metadata: Mapping[str, Any]) -> bool:
    """True when metadata claims an Agent surface, in either boolean or string form."""

    raw = metadata.get(AGENT_SURFACE_METADATA_KEY)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().casefold() in {"true", "1", "yes"}
    if isinstance(raw, (int, float)):
        return bool(raw)
    return False


def _environment_matches(metadata: Mapping[str, Any], environment: str) -> bool:
    value = metadata.get(ENVIRONMENT_METADATA_KEY)
    return isinstance(value, str) and value.strip().casefold() == environment.strip().casefold()


def _canonical_id(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        return str(UUID(text))
    except ValueError:
        return text


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.strip()))
    except ValueError:
        return None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def policy_from_settings(
    *,
    environment: str,
    session_timeout_seconds: float,
    lease_grace_seconds: float = 120.0,
    startup_grace_seconds: float = 180.0,
    max_terminations: int = 25,
    match_environment: bool = True,
) -> ReconciliationPolicy:
    """Build a policy from process settings without importing Settings here."""

    return ReconciliationPolicy(
        environment=environment,
        lease_ttl_seconds=float(session_timeout_seconds),
        lease_grace_seconds=lease_grace_seconds,
        startup_grace_seconds=startup_grace_seconds,
        max_terminations=max_terminations,
        match_environment=match_environment,
    )
