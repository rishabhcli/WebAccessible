"""Push consented routine reminders to the participant instead of waiting to be polled.

Reminders used to exist only as a pull: the app fetched `/v1/reminders` while the routine
chooser happened to be mounted. A suggestion that becomes due a minute later, or while the
participant is looking at any other screen, was never surfaced. This scheduler evaluates
due reminders for participants who currently have the app open and publishes them on the
participant topic, so the nudge arrives on its own.

The permission boundary is unchanged. A pushed reminder is a dismissible suggestion; only
the participant accepting it may open a routine, and every page action stays theirs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from backend.app.contracts.models import ProactiveReminder
from backend.app.services.event_hub import SessionEventHub, user_topic

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Watcher:
    user_id: str
    participant_session_id: UUID | str
    announced: set[str] = field(default_factory=set)
    subscriptions: int = 0


class ProactiveReminderScheduler:
    """Evaluate and publish due reminders for participants with the app open."""

    def __init__(
        self,
        *,
        orchestrator: Any,
        event_hub: SessionEventHub,
        scan_interval_seconds: float = 60.0,
    ) -> None:
        if scan_interval_seconds <= 0:
            raise ValueError("scan_interval_seconds must be positive")
        self.orchestrator = orchestrator
        self.event_hub = event_hub
        self.scan_interval_seconds = scan_interval_seconds
        self._watchers: dict[str, _Watcher] = {}
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._runner is not None and not self._runner.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._runner = asyncio.create_task(
            self._run(),
            name="webaccessible-proactive-reminders",
        )

    async def stop(self) -> None:
        runner = self._runner
        if runner is None:
            return
        self._stop_event.set()
        self._wake_event.set()
        runner.cancel()
        try:
            await runner
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self._runner = None

    async def attach(self, user_id: str, participant_session_id: UUID | str) -> None:
        """Register an open app and evaluate immediately so nothing waits for the next scan."""

        async with self._lock:
            watcher = self._watchers.get(user_id)
            if watcher is None:
                watcher = _Watcher(user_id=user_id, participant_session_id=participant_session_id)
                self._watchers[user_id] = watcher
            watcher.participant_session_id = participant_session_id
            watcher.subscriptions += 1
        self._wake_event.set()
        await self._evaluate(self._watchers[user_id])

    async def detach(self, user_id: str) -> None:
        async with self._lock:
            watcher = self._watchers.get(user_id)
            if watcher is None:
                return
            watcher.subscriptions -= 1
            if watcher.subscriptions <= 0:
                self._watchers.pop(user_id, None)

    def forget(self, user_id: str, reminder_id: str) -> None:
        """Allow a reminder to be re-announced after the participant acts on it."""

        watcher = self._watchers.get(user_id)
        if watcher is not None:
            watcher.announced.discard(reminder_id)

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=self.scan_interval_seconds,
                    )
                except TimeoutError:
                    pass
                self._wake_event.clear()
                if self._stop_event.is_set():
                    break
                async with self._lock:
                    watchers = list(self._watchers.values())
                for watcher in watchers:
                    await self._evaluate(watcher)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("The proactive reminder scheduler stopped unexpectedly.")

    async def _evaluate(self, watcher: _Watcher) -> None:
        try:
            reminders = await self.orchestrator.reminders(
                watcher.user_id,
                watcher.participant_session_id,
            )
        except Exception:
            logger.warning(
                "Could not evaluate proactive reminders for the current participant; "
                "the next scan will retry.",
            )
            return
        active = {reminder.id for reminder in reminders}
        watcher.announced &= active
        for reminder in reminders:
            if reminder.id in watcher.announced:
                continue
            watcher.announced.add(reminder.id)
            await self.event_hub.publish(
                user_topic(watcher.user_id),
                _reminder_event(reminder),
            )


def _reminder_event(reminder: ProactiveReminder) -> dict[str, Any]:
    return {
        "type": "proactive_reminder",
        "reminder": reminder.model_dump(mode="json"),
        "published_at": datetime.now(UTC).isoformat(),
    }
