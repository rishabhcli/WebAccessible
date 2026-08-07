from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any

from backend.app.integrations.snowflake import SnowflakeAdapter, SnowflakeProviderError
from backend.app.persistence.repository import OperationalRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TelemetryFlushResult:
    selected: int = 0
    synced: int = 0
    failed: int = 0
    deferred: int = 0


class TelemetryService:
    """Drain the durable operational outbox into idempotent Snowflake MERGEs."""

    def __init__(
        self,
        repository: OperationalRepository,
        snowflake: SnowflakeAdapter,
        *,
        poll_interval_seconds: float = 1.0,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 60.0,
        batch_size: int = 100,
        scan_limit: int = 1000,
        max_concurrency: int = 8,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if retry_base_seconds <= 0:
            raise ValueError("retry_base_seconds must be positive")
        if retry_max_seconds < retry_base_seconds:
            raise ValueError("retry_max_seconds must be at least retry_base_seconds")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if scan_limit < batch_size:
            raise ValueError("scan_limit must be at least batch_size")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")

        self.repository = repository
        self.snowflake = snowflake
        self.poll_interval_seconds = poll_interval_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.batch_size = batch_size
        self.scan_limit = scan_limit
        self.max_concurrency = max_concurrency

        self._flush_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._retry_at: dict[str, float] = {}

    @property
    def running(self) -> bool:
        return self._runner is not None and not self._runner.done()

    async def start(self) -> None:
        """Start one idempotent background drain loop."""

        if self.running:
            return
        if self._runner is not None:
            await self._consume_finished_runner()
        self._stop_event.clear()
        self._wake_event.clear()
        self._runner = asyncio.create_task(
            self._run(),
            name="webaccessible-snowflake-telemetry",
        )

    async def stop(self, *, flush: bool = True) -> TelemetryFlushResult:
        """Stop the background loop and optionally make one final forced drain."""

        runner = self._runner
        if runner is not None:
            self._stop_event.set()
            self._wake_event.set()
            try:
                await runner
            finally:
                self._runner = None
        if flush:
            return await self.flush(force=True)
        return TelemetryFlushResult()

    async def flush(self, *, force: bool = False) -> TelemetryFlushResult:
        """Attempt one bounded outbox batch without changing any stable payload IDs."""

        async with self._flush_lock:
            rows = await asyncio.to_thread(
                self.repository.pending_outbox,
                self.scan_limit,
            )
            now = monotonic()
            eligible: list[dict[str, Any]] = []
            deferred = 0
            for row in rows:
                item_id = str(row.get("id") or "")
                retry_at = self._retry_at.get(item_id, 0.0)
                if force or retry_at <= now:
                    eligible.append(row)
                    if len(eligible) >= self.batch_size:
                        break
                else:
                    deferred += 1

            semaphore = asyncio.Semaphore(self.max_concurrency)

            async def sync_bounded(row: dict[str, Any]) -> bool:
                async with semaphore:
                    return await self._sync_item(row)

            outcomes = await asyncio.gather(*(sync_bounded(row) for row in eligible))
            synced = sum(outcomes)
            failed = len(outcomes) - synced

            return TelemetryFlushResult(
                selected=len(eligible),
                synced=synced,
                failed=failed,
                deferred=deferred,
            )

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                result = await self.flush()
                if result.selected >= self.batch_size and result.failed == 0:
                    continue

                self._wake_event.clear()
                if self._stop_event.is_set():
                    break
                timeout = self._next_wait_seconds()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telemetry drain stopped after an unexpected service error.")

    async def _sync_item(self, row: dict[str, Any]) -> bool:
        item_id = str(row.get("id") or "")
        stable_key = str(row.get("stable_key") or "")
        kind = str(row.get("kind") or "")
        payload_value = row.get("payload")

        if not item_id or not stable_key or not kind or not isinstance(payload_value, dict):
            await self._record_failure(
                row,
                item_id=item_id,
                kind=kind,
                stable_key=stable_key,
                error_code="invalid_outbox_item",
                retryable=False,
            )
            return False

        # Do not inject, replace, or regenerate identifier fields here. The payload
        # was created in the same transaction as the operational state change, and
        # SnowflakeAdapter validates its table-specific stable key before MERGE.
        payload = dict(payload_value)
        try:
            synchronized = await self.snowflake.sync_outbox(kind, payload)
            if synchronized is not True:
                raise RuntimeError("Snowflake did not acknowledge the outbox item")
            await asyncio.to_thread(
                self.repository.mark_outbox,
                item_id,
                synced=True,
                error_code=None,
            )
        except Exception as exc:
            await self._record_failure(
                row,
                item_id=item_id,
                kind=kind,
                stable_key=stable_key,
                error_code=_error_code(exc),
                retryable=isinstance(exc, SnowflakeProviderError) and exc.retryable,
            )
            return False

        self._retry_at.pop(item_id, None)
        return True

    async def _record_failure(
        self,
        row: dict[str, Any],
        *,
        item_id: str,
        kind: str,
        stable_key: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        if item_id:
            try:
                await asyncio.to_thread(
                    self.repository.mark_outbox,
                    item_id,
                    synced=False,
                    error_code=error_code,
                )
            except Exception:
                logger.exception(
                    "Could not update failed telemetry item %s (%s).",
                    stable_key or item_id,
                    kind or "unknown",
                )

            attempt_number = max(int(row.get("attempts") or 0) + 1, 1)
            delay = self._retry_delay(attempt_number)
            if not retryable:
                delay = self.retry_max_seconds
            self._retry_at[item_id] = monotonic() + delay

        logger.warning(
            "Telemetry synchronization failed for %s item %s: %s.",
            kind or "unknown",
            stable_key or item_id or "unknown",
            error_code,
        )

    def _retry_delay(self, attempt_number: int) -> float:
        exponent = min(max(attempt_number - 1, 0), 30)
        return min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2.0**exponent),
        )

    def _next_wait_seconds(self) -> float:
        if not self._retry_at:
            return self.poll_interval_seconds
        retry_delay = max(min(self._retry_at.values()) - monotonic(), 0.0)
        return min(self.poll_interval_seconds, retry_delay)

    async def _consume_finished_runner(self) -> None:
        runner = self._runner
        self._runner = None
        if runner is None or runner.cancelled():
            return
        exception = runner.exception()
        if exception is not None:
            raise exception


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    value = getattr(code, "value", code)
    if value:
        return str(value)
    return type(exc).__name__
