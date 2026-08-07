"""Narrow Browserbase Browser Session integration.

This module intentionally exposes no Browserbase Agent, click, type, fill, or
submit capability. Page observation and non-activating highlighting connect via
the returned server-only CDP URL in the browser bridge.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from time import monotonic
from typing import Any, Final, Literal
from urllib.parse import urlsplit

import browserbase
from browserbase import AsyncBrowserbase, omit
from browserbase.types.session_create_params import BrowserSettings

from backend.app.config import Settings

_TERMINAL_STATUSES: Final = frozenset({"ERROR", "TIMED_OUT", "COMPLETED"})

SessionStatus = Literal["PENDING", "RUNNING", "ERROR", "TIMED_OUT", "COMPLETED"]

#: Provider statuses that no longer consume a managed browser slot.
TERMINAL_SESSION_STATUSES: Final = _TERMINAL_STATUSES
#: Provider statuses that still consume a managed browser slot and can be billed.
LIVE_SESSION_STATUSES: Final = frozenset({"PENDING", "RUNNING"})

#: ``user_metadata`` keys written by :meth:`BrowserbaseProvider.create`. Ownership
#: reconciliation reads these back, so the literals live in one place.
OWNER_METADATA_KEY: Final = "webaccessibleSessionId"
ENVIRONMENT_METADATA_KEY: Final = "environment"
AGENT_SURFACE_METADATA_KEY: Final = "agentSurfaceUsed"


class BrowserbaseErrorCode(StrEnum):
    UNCONFIGURED = "unconfigured"
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    SESSION_LIMIT = "session_limit"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    DISCONNECTED = "disconnected"
    TERMINATION_FAILED = "termination_failed"
    INVALID_RESPONSE = "invalid_response"


class BrowserbaseProviderError(RuntimeError):
    """A sanitized Browserbase failure suitable for readiness state."""

    def __init__(
        self,
        code: BrowserbaseErrorCode,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class BrowserSession:
    id: str
    status: str
    region: str
    keep_alive: bool
    created_at: datetime
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class LiveViewPage:
    id: str
    debugger_fullscreen_url: str
    debugger_url: str
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class LiveView:
    session_id: str
    debugger_fullscreen_url: str
    debugger_url: str
    pages: tuple[LiveViewPage, ...]


@dataclass(frozen=True, slots=True)
class BrowserConnectData:
    """Server-only connection material; never include this in a web response."""

    session_id: str
    cdp_url: str


@dataclass(frozen=True, slots=True)
class BrowserbaseSessionData:
    id: str
    connect_url: str
    status: str
    start_url: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TerminationResult:
    session_id: str
    status: str
    already_terminal: bool
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Read-only provider session facts used by lifecycle reconciliation.

    This record deliberately carries no ``connect_url``, Selenium URL, signing key,
    or Live View material even when the underlying provider response contains them.
    """

    id: str
    status: str
    region: str
    keep_alive: bool
    created_at: datetime
    started_at: datetime
    expires_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    user_metadata: Mapping[str, Any]


class BrowserbaseProvider:
    """Browserbase lifecycle API with the only four product-authorized operations."""

    __slots__ = (
        "_api_key",
        "_keep_alive",
        "_log_session",
        "_operational_database_path",
        "_record_session",
        "_region",
        "_request_timeout",
        "_runtime_mode",
        "_session_timeout",
    )

    def __init__(self, settings: Settings) -> None:
        if settings.browserbase_api_key is None:
            raise BrowserbaseProviderError(
                BrowserbaseErrorCode.UNCONFIGURED,
                "Browserbase is not configured.",
                retryable=False,
            )
        self._api_key = settings.browserbase_api_key.get_secret_value()
        self._region = settings.browserbase_region
        self._session_timeout = settings.browserbase_session_timeout_seconds
        self._request_timeout = settings.browserbase_request_timeout_seconds
        self._keep_alive = settings.browserbase_keep_alive
        self._record_session = settings.browserbase_record_session
        self._log_session = settings.browserbase_log_session
        self._runtime_mode = settings.app_env.value
        self._operational_database_path = settings.operational_database_path

    async def create(
        self,
        webaccessible_session_id: str,
        *,
        allowed_domains: Sequence[str] = (),
    ) -> BrowserSession:
        """Create one managed session without exposing its CDP URL."""

        if not webaccessible_session_id.strip():
            raise ValueError("webaccessible_session_id must not be blank")
        domains = _normalize_domains(allowed_domains)
        browser_settings: BrowserSettings = {
            "record_session": self._record_session,
            "log_session": self._log_session,
        }
        if domains:
            browser_settings["allowed_domains"] = list(domains)

        try:
            async with self._client() as client:
                session = await client.sessions.create(
                    keep_alive=self._keep_alive,
                    region=self._region,
                    api_timeout=self._session_timeout,
                    browser_settings=browser_settings,
                    user_metadata={
                        OWNER_METADATA_KEY: webaccessible_session_id,
                        ENVIRONMENT_METADATA_KEY: self._runtime_mode,
                        AGENT_SURFACE_METADATA_KEY: "false",
                    },
                )
        except Exception as exc:
            raise _map_error(exc) from exc
        return _session_from_sdk(session)

    async def get_live_view(self, session_id: str) -> LiveView:
        """Return interactive Live View URLs for an authorized active session."""

        _require_session_id(session_id)
        try:
            async with self._client() as client:
                links = await client.sessions.debug(session_id)
        except Exception as exc:
            raise _map_error(exc) from exc

        if not links.debugger_fullscreen_url:
            raise BrowserbaseProviderError(
                BrowserbaseErrorCode.INVALID_RESPONSE,
                "Browserbase did not return an interactive Live View URL.",
                retryable=True,
            )
        pages = tuple(
            LiveViewPage(
                id=page.id,
                debugger_fullscreen_url=page.debugger_fullscreen_url,
                debugger_url=page.debugger_url,
                title=page.title,
                url=page.url,
            )
            for page in links.pages
        )
        return LiveView(
            session_id=session_id,
            debugger_fullscreen_url=links.debugger_fullscreen_url,
            debugger_url=links.debugger_url,
            pages=pages,
        )

    async def connect_data(self, session_id: str) -> BrowserConnectData:
        """Retrieve the CDP URL for server-side Playwright attachment."""

        _require_session_id(session_id)
        try:
            async with self._client() as client:
                session = await client.sessions.retrieve(session_id)
        except Exception as exc:
            raise _map_error(exc) from exc

        if session.status in _TERMINAL_STATUSES or not session.connect_url:
            raise BrowserbaseProviderError(
                BrowserbaseErrorCode.DISCONNECTED,
                "The Browserbase session is no longer connectable.",
                retryable=False,
            )
        return BrowserConnectData(session_id=session_id, cdp_url=session.connect_url)

    async def terminate(self, session_id: str) -> TerminationResult:
        """Idempotently request provider-confirmed release of a session."""

        _require_session_id(session_id)
        try:
            async with self._client() as client:
                current = await client.sessions.retrieve(session_id)
                if current.status in _TERMINAL_STATUSES:
                    return TerminationResult(
                        session_id=session_id,
                        status=current.status,
                        already_terminal=True,
                        ended_at=current.ended_at,
                    )
                stopped = await client.sessions.update(session_id, status="REQUEST_RELEASE")
                deadline = monotonic() + min(max(self._request_timeout, 1.0), 10.0)
                while stopped.status not in _TERMINAL_STATUSES and monotonic() < deadline:
                    await asyncio.sleep(0.25)
                    stopped = await client.sessions.retrieve(session_id)
                if stopped.status not in _TERMINAL_STATUSES:
                    raise BrowserbaseProviderError(
                        BrowserbaseErrorCode.TERMINATION_FAILED,
                        "Browserbase did not confirm that the session stopped.",
                        retryable=True,
                    )
        except Exception as exc:
            mapped = _map_error(exc)
            raise BrowserbaseProviderError(
                BrowserbaseErrorCode.TERMINATION_FAILED,
                "Browserbase did not confirm the session termination request.",
                retryable=mapped.retryable,
                status_code=mapped.status_code,
            ) from exc
        return TerminationResult(
            session_id=session_id,
            status=stopped.status,
            already_terminal=False,
            ended_at=stopped.ended_at,
        )

    async def reconcile_orphans(self) -> int:
        """Release owned sessions that operational state proves are orphaned.

        Delegates to the reconciliation subsystem, which compares provider sessions
        against the operational SQLite record and applies a startup grace, lease
        bound, and blast-radius bound before terminating anything. Listing every
        owned live session and stopping it would kill sessions that are in use.

        The import is deferred because the reconciliation module builds on this one.
        Returns the number of provider-confirmed releases; never raises on provider
        or local-state failure, so a sweep cannot block application startup.
        """

        from backend.app.services.browser_reconciliation import (
            BrowserReconciliationService,
            LocalStateUnavailableError,
            SqliteLocalSessionStore,
            policy_from_settings,
        )

        try:
            local_state = SqliteLocalSessionStore(
                self._operational_database_path,
                writable=True,
            )
            service = BrowserReconciliationService(
                provider=self,
                local_state=local_state,
                policy=policy_from_settings(
                    environment=self._runtime_mode,
                    session_timeout_seconds=self._session_timeout,
                ),
            )
            report = await service.reconcile(execute=True)
        except (LocalStateUnavailableError, BrowserbaseProviderError):
            return 0
        return report.counts["terminated"]

    async def list_sessions(
        self,
        *,
        status: SessionStatus | None = None,
        owner_environment: str | None = None,
    ) -> tuple[SessionRecord, ...]:
        """List provider sessions, optionally narrowed by owner metadata.

        Read-only. ``owner_environment`` is translated into the provider's
        ``user_metadata`` query so WebAccessible-owned sessions can be selected
        server-side; callers must still verify ownership on the returned records.
        """

        query = _owner_metadata_query(owner_environment) if owner_environment else None
        try:
            async with self._client() as client:
                sessions = await client.sessions.list(
                    q=query if query is not None else omit,
                    status=status if status is not None else omit,
                )
        except Exception as exc:
            raise _map_error(exc) from exc
        return tuple(_record_from_sdk(session) for session in sessions)

    async def session_status(self, session_id: str) -> SessionRecord:
        """Read one session's lifecycle status without exposing connect material."""

        _require_session_id(session_id)
        try:
            async with self._client() as client:
                session = await client.sessions.retrieve(session_id)
        except Exception as exc:
            raise _map_error(exc) from exc
        return _record_from_sdk(session)

    def _client(self) -> AsyncBrowserbase:
        return AsyncBrowserbase(
            api_key=self._api_key,
            timeout=self._request_timeout,
            max_retries=2,
        )


class BrowserbaseAdapter:
    """Application-facing Browserbase contract used by the session service."""

    __slots__ = ("_provider",)

    def __init__(self, settings: Settings) -> None:
        self._provider = BrowserbaseProvider(settings)

    async def create_session(
        self,
        start_url: str,
        metadata: dict[str, Any],
    ) -> BrowserbaseSessionData:
        parsed = urlsplit(start_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("start_url must be an absolute http(s) URL")
        web_session_id = str(
            metadata.get("webaccessible_session_id")
            or metadata.get("web_session_id")
            or metadata.get("session_id")
            or ""
        )
        if not web_session_id:
            raise ValueError("metadata must include the WebAccessible session ID")
        # Errands routinely hand off to another provider (DMV -> Qmatic, retailer ->
        # checkout, salon -> scheduler).  Do not turn the starting host into a provider
        # allowlist; safety is enforced per action, not by breaking legitimate navigation.
        session = await self._provider.create(web_session_id)
        connect = await self._provider.connect_data(session.id)
        return BrowserbaseSessionData(
            id=session.id,
            connect_url=connect.cdp_url,
            status=session.status,
            start_url=start_url,
            created_at=session.created_at,
        )

    async def get_live_view(self, session_id: str) -> str:
        live_view = await self._provider.get_live_view(session_id)
        return live_view.debugger_fullscreen_url

    async def connect_data(self, session_id: str) -> BrowserConnectData:
        return await self._provider.connect_data(session_id)

    async def terminate(self, session_id: str) -> bool:
        await self._provider.terminate(session_id)
        return True

    async def reconcile_orphans(self) -> int:
        return await self._provider.reconcile_orphans()


def _session_from_sdk(session: Any) -> BrowserSession:
    return BrowserSession(
        id=session.id,
        status=session.status,
        region=session.region,
        keep_alive=session.keep_alive,
        created_at=session.created_at,
        started_at=session.started_at,
        expires_at=session.expires_at,
        ended_at=session.ended_at,
    )


def _record_from_sdk(session: Any) -> SessionRecord:
    """Project any provider session payload onto the sanitized read record."""

    metadata = getattr(session, "user_metadata", None)
    return SessionRecord(
        id=session.id,
        status=session.status,
        region=session.region,
        keep_alive=session.keep_alive,
        created_at=session.created_at,
        started_at=session.started_at,
        expires_at=session.expires_at,
        updated_at=session.updated_at,
        ended_at=session.ended_at,
        user_metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def _owner_metadata_query(environment: str) -> str:
    """Build the provider ``user_metadata`` filter for one WebAccessible environment."""

    value = environment.strip()
    if not value or any(character in value for character in "'[]\\"):
        raise ValueError("owner_environment must be a plain metadata value")
    return f"user_metadata['{ENVIRONMENT_METADATA_KEY}']:'{value}'"


def _require_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise ValueError("session_id must not be blank")


# Ownership classification lives in
# ``backend.app.services.browser_reconciliation``, which judges it against
# operational state rather than provider metadata alone.


def _normalize_domains(domains: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for domain in domains:
        value = domain.strip().lower().rstrip(".")
        if not value or "://" in value or "/" in value:
            raise ValueError("allowed_domains entries must be host names")
        normalized.append(value)
    return tuple(dict.fromkeys(normalized))


def _map_error(exc: Exception) -> BrowserbaseProviderError:
    if isinstance(exc, BrowserbaseProviderError):
        return exc
    if isinstance(exc, browserbase.AuthenticationError | browserbase.PermissionDeniedError):
        return BrowserbaseProviderError(
            BrowserbaseErrorCode.UNAUTHORIZED,
            "Browserbase rejected the configured credentials.",
            retryable=False,
            status_code=getattr(exc, "status_code", None),
        )
    if isinstance(exc, browserbase.APITimeoutError):
        return BrowserbaseProviderError(
            BrowserbaseErrorCode.TIMEOUT,
            "Browserbase did not respond before the request timeout.",
            retryable=True,
        )
    if isinstance(exc, browserbase.APIConnectionError):
        return BrowserbaseProviderError(
            BrowserbaseErrorCode.UNREACHABLE,
            "Browserbase is unreachable.",
            retryable=True,
        )
    if isinstance(exc, browserbase.NotFoundError):
        return BrowserbaseProviderError(
            BrowserbaseErrorCode.DISCONNECTED,
            "The Browserbase session does not exist or is no longer available.",
            retryable=False,
            status_code=404,
        )
    if isinstance(exc, browserbase.RateLimitError):
        body = str(getattr(exc, "body", "")).lower()
        if "session" in body and ("limit" in body or "concurr" in body):
            code = BrowserbaseErrorCode.SESSION_LIMIT
        elif "capacity" in body or "browser hour" in body:
            code = BrowserbaseErrorCode.CAPACITY_EXHAUSTED
        else:
            code = BrowserbaseErrorCode.RATE_LIMITED
        return BrowserbaseProviderError(
            code,
            "Browserbase temporarily rejected the session request.",
            retryable=True,
            status_code=429,
        )
    if isinstance(exc, browserbase.APIResponseValidationError):
        return BrowserbaseProviderError(
            BrowserbaseErrorCode.INVALID_RESPONSE,
            "Browserbase returned an invalid response.",
            retryable=True,
            status_code=getattr(exc, "status_code", None),
        )
    if isinstance(exc, browserbase.APIStatusError):
        retryable = exc.status_code >= 500 or exc.status_code in {408, 409, 425}
        return BrowserbaseProviderError(
            (
                BrowserbaseErrorCode.UNREACHABLE
                if retryable
                else BrowserbaseErrorCode.INVALID_RESPONSE
            ),
            "Browserbase could not complete the session operation.",
            retryable=retryable,
            status_code=exc.status_code,
        )
    return BrowserbaseProviderError(
        BrowserbaseErrorCode.INVALID_RESPONSE,
        "Browserbase could not complete the session operation.",
        retryable=False,
    )
