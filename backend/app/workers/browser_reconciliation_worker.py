"""Runner for Browserbase lifecycle reconciliation.

Supports one-shot execution and a bounded periodic loop. The loop is bounded by
construction: it always stops at a cycle count, a wall-clock deadline, a
consecutive-failure limit, or an explicit stop request, so it can never become an
unattended process that keeps calling a paid provider forever.

Dry run is the default here as well; ``execute`` must be set deliberately.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings
from backend.app.integrations.browserbase.client import (
    BrowserbaseProvider,
    BrowserbaseProviderError,
)
from backend.app.services.browser_reconciliation import (
    BrowserReconciliationService,
    LocalSessionStore,
    LocalStateUnavailableError,
    ReconciliationPolicy,
    ReconciliationProvider,
    ReconciliationReport,
    SqliteLocalSessionStore,
    policy_from_settings,
    sanitize,
)

__all__ = [
    "BrowserReconciliationWorker",
    "WorkerSchedule",
    "build_reconciliation_service",
    "build_reconciliation_worker",
]

LOGGER_NAME = "webaccessible.browser_reconciliation"

ReportSink = Callable[[ReconciliationReport], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class WorkerSchedule:
    """Bounds for a periodic run. ``max_cycles=1`` is the one-shot default."""

    interval_seconds: float = 300.0
    max_cycles: int | None = 1
    max_runtime_seconds: float | None = None
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self.max_cycles is not None and self.max_cycles < 1:
            raise ValueError("max_cycles must be at least 1 when set")
        if self.max_runtime_seconds is not None and self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be positive when set")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")
        if self.max_cycles is None and self.max_runtime_seconds is None:
            raise ValueError("a periodic run must be bounded by max_cycles or max_runtime_seconds")


class BrowserReconciliationWorker:
    """Drives :class:`BrowserReconciliationService` once or on a bounded schedule."""

    __slots__ = ("_execute", "_logger", "_on_report", "_schedule", "_service", "_stop")

    def __init__(
        self,
        service: BrowserReconciliationService,
        *,
        execute: bool = False,
        schedule: WorkerSchedule | None = None,
        on_report: ReportSink | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._service = service
        self._execute = execute
        self._schedule = schedule or WorkerSchedule()
        self._on_report = on_report
        self._logger = logger or logging.getLogger(LOGGER_NAME)
        self._stop = asyncio.Event()

    @property
    def execute(self) -> bool:
        return self._execute

    @property
    def schedule(self) -> WorkerSchedule:
        return self._schedule

    def request_stop(self) -> None:
        """Ask a running loop to finish after the current cycle."""

        self._stop.set()

    async def run_once(self) -> ReconciliationReport:
        """Run exactly one reconciliation pass and emit its sanitized report."""

        report = await self._service.reconcile(execute=self._execute)
        await self._emit(report)
        return report

    async def run(self) -> list[ReconciliationReport]:
        """Run the bounded periodic loop and return every completed report."""

        self._stop.clear()
        reports: list[ReconciliationReport] = []
        deadline = (
            None
            if self._schedule.max_runtime_seconds is None
            else asyncio.get_running_loop().time() + self._schedule.max_runtime_seconds
        )
        consecutive_failures = 0
        cycle = 0

        while not self._stop.is_set():
            cycle += 1
            try:
                report = await self.run_once()
            except (BrowserbaseProviderError, LocalStateUnavailableError) as error:
                consecutive_failures += 1
                self._log_cycle_error(cycle, error)
            else:
                reports.append(report)
                consecutive_failures = 0 if report.ok else consecutive_failures + 1

            if consecutive_failures >= self._schedule.max_consecutive_failures:
                self._logger.error(
                    "browser reconciliation stopped after %d consecutive failed cycles",
                    consecutive_failures,
                )
                break
            if self._schedule.max_cycles is not None and cycle >= self._schedule.max_cycles:
                break
            if not await self._wait_for_next_cycle(deadline):
                break

        return reports

    async def _wait_for_next_cycle(self, deadline: float | None) -> bool:
        """Sleep until the next cycle. Returns False when the loop must end."""

        delay = self._schedule.interval_seconds
        if deadline is not None:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            delay = min(delay, remaining)
            if remaining - delay <= 0:
                # The next cycle would start at or past the deadline.
                return False
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except TimeoutError:
            return True
        return False

    async def _emit(self, report: ReconciliationReport) -> None:
        payload = report.to_dict()
        level = logging.INFO if report.ok else logging.WARNING
        self._logger.log(level, json.dumps(payload, separators=(",", ":"), sort_keys=True))
        if self._on_report is None:
            return
        result = self._on_report(report)
        if asyncio.iscoroutine(result):
            await result

    def _log_cycle_error(self, cycle: int, error: Exception) -> None:
        detail: dict[str, Any] = {
            "event": "browser_reconciliation_cycle_failed",
            "cycle": cycle,
            "error_type": type(error).__name__,
        }
        if isinstance(error, BrowserbaseProviderError):
            detail["error_code"] = error.code.value
            detail["retryable"] = error.retryable
        self._logger.warning(json.dumps(sanitize(detail), separators=(",", ":"), sort_keys=True))


def build_reconciliation_service(
    settings: Settings,
    *,
    execute: bool = False,
    policy: ReconciliationPolicy | None = None,
    provider: ReconciliationProvider | None = None,
    local_state: LocalSessionStore | None = None,
) -> BrowserReconciliationService:
    """Assemble the service from process settings.

    Raises :class:`BrowserbaseProviderError` when Browserbase is unconfigured and
    :class:`LocalStateUnavailableError` when the operational database is missing;
    neither condition is papered over with a fake success.
    """

    resolved_policy = policy or policy_from_settings(
        environment=settings.app_env.value,
        session_timeout_seconds=settings.browserbase_session_timeout_seconds,
    )
    resolved_provider = provider if provider is not None else BrowserbaseProvider(settings)
    resolved_local = (
        local_state
        if local_state is not None
        else SqliteLocalSessionStore(
            settings.operational_database_path,
            writable=execute,
        )
    )
    return BrowserReconciliationService(
        provider=resolved_provider,
        local_state=resolved_local,
        policy=resolved_policy,
    )


def build_reconciliation_worker(
    settings: Settings,
    *,
    execute: bool = False,
    schedule: WorkerSchedule | None = None,
    policy: ReconciliationPolicy | None = None,
    provider: ReconciliationProvider | None = None,
    local_state: LocalSessionStore | None = None,
    on_report: ReportSink | None = None,
    logger: logging.Logger | None = None,
) -> BrowserReconciliationWorker:
    """One-call construction for an application hook or the CLI script."""

    service = build_reconciliation_service(
        settings,
        execute=execute,
        policy=policy,
        provider=provider,
        local_state=local_state,
    )
    return BrowserReconciliationWorker(
        service,
        execute=execute,
        schedule=schedule,
        on_report=on_report,
        logger=logger,
    )
