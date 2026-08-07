from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.app.contracts.models import (
    ProactiveReminder,
    RecurrenceKind,
    RoutinePattern,
    RoutineSummary,
    SessionMode,
    SessionState,
    SessionView,
)
from backend.app.persistence.repository import OperationalRepository
from backend.app.services.activity_memory import ActivityMemoryService
from backend.app.services.event_hub import SessionEventHub, user_topic
from backend.app.services.proactive import ProactiveReminderScheduler


class _Everos:
    def __init__(self) -> None:
        self.foresight_writes: list[dict[str, Any]] = []

    async def save_activity_memory(self, *_args: object, **_kwargs: object) -> dict[str, str]:
        return {"status": "accepted"}

    async def save_foresight(
        self,
        user_id: str,
        pattern: dict[str, Any],
        *,
        last_completed_at: str | None = None,
    ) -> dict[str, Any]:
        self.foresight_writes.append(
            {"user_id": user_id, "pattern": pattern, "last_completed_at": last_completed_at}
        )
        return {"status": "accepted"}


class _StubOrchestrator:
    def __init__(self, reminders: list[ProactiveReminder]) -> None:
        self.reminders_to_return = reminders
        self.calls = 0
        self.failure: Exception | None = None

    async def reminders(
        self,
        _user_id: str,
        _participant_session_id: Any,
    ) -> list[ProactiveReminder]:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return list(self.reminders_to_return)


def _reminder(reminder_id: str, task_name: str = "Book haircut") -> ProactiveReminder:
    return ProactiveReminder(
        id=reminder_id,
        routine=RoutineSummary(
            id="skill-haircut",
            name=task_name,
            start_url="https://salon.example/",
        ),
        reason=f"You last did {task_name} about a month ago. Would you like to do it now?",
        due_at=datetime(2026, 9, 5, 17, tzinfo=UTC),
        pattern=RoutinePattern(
            task_id="task-haircut",
            task_name=task_name,
            recurrence=RecurrenceKind.MONTHLY,
            occurrence_count=3,
            typical_local_time="10:00",
            timezone="America/Los_Angeles",
            next_due_at=datetime(2026, 9, 5, 17, tzinfo=UTC),
            confidence=0.8,
        ),
        overdue_days=4,
    )


class ProactiveSchedulerTests(unittest.TestCase):
    def test_attaching_publishes_a_due_reminder_without_waiting_for_a_poll(self) -> None:
        hub = SessionEventHub()
        orchestrator = _StubOrchestrator([_reminder("reminder-1")])
        scheduler = ProactiveReminderScheduler(
            orchestrator=orchestrator,
            event_hub=hub,
            scan_interval_seconds=60.0,
        )
        received: list[dict[str, Any]] = []

        async def scenario() -> None:
            async def listen() -> None:
                async for event in hub.subscribe(user_topic("margaret")):
                    if event.get("type") == "keepalive":
                        continue
                    received.append(event)
                    break

            listener = asyncio.create_task(listen())
            await asyncio.sleep(0)
            await scheduler.attach("margaret", uuid4())
            await asyncio.wait_for(listener, timeout=2)

        asyncio.run(scenario())

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["type"], "proactive_reminder")
        self.assertEqual(received[0]["reminder"]["id"], "reminder-1")
        self.assertIn("about a month ago", received[0]["reminder"]["reason"])

    def test_the_same_reminder_is_announced_only_once(self) -> None:
        hub = SessionEventHub()
        orchestrator = _StubOrchestrator([_reminder("reminder-1")])
        scheduler = ProactiveReminderScheduler(
            orchestrator=orchestrator,
            event_hub=hub,
            scan_interval_seconds=60.0,
        )
        received: list[dict[str, Any]] = []

        async def scenario() -> None:
            async def listen() -> None:
                async for event in hub.subscribe(user_topic("margaret")):
                    if event.get("type") != "keepalive":
                        received.append(event)

            listener = asyncio.create_task(listen())
            await asyncio.sleep(0)
            participant = uuid4()
            await scheduler.attach("margaret", participant)
            await scheduler.attach("margaret", participant)
            await asyncio.sleep(0.05)
            listener.cancel()

        asyncio.run(scenario())

        self.assertEqual(len(received), 1)
        self.assertEqual(orchestrator.calls, 2)

    def test_a_dismissed_reminder_can_be_announced_again_after_it_is_forgotten(self) -> None:
        hub = SessionEventHub()
        orchestrator = _StubOrchestrator([_reminder("reminder-1")])
        scheduler = ProactiveReminderScheduler(
            orchestrator=orchestrator,
            event_hub=hub,
            scan_interval_seconds=60.0,
        )
        received: list[dict[str, Any]] = []

        async def scenario() -> None:
            async def listen() -> None:
                async for event in hub.subscribe(user_topic("margaret")):
                    if event.get("type") != "keepalive":
                        received.append(event)

            listener = asyncio.create_task(listen())
            await asyncio.sleep(0)
            participant = uuid4()
            await scheduler.attach("margaret", participant)
            scheduler.forget("margaret", "reminder-1")
            await scheduler.attach("margaret", participant)
            await asyncio.sleep(0.05)
            listener.cancel()

        asyncio.run(scenario())

        self.assertEqual(len(received), 2)

    def test_an_evaluation_failure_does_not_stop_the_scheduler(self) -> None:
        hub = SessionEventHub()
        orchestrator = _StubOrchestrator([_reminder("reminder-1")])
        orchestrator.failure = RuntimeError("EverOS is unreachable")
        scheduler = ProactiveReminderScheduler(
            orchestrator=orchestrator,
            event_hub=hub,
            scan_interval_seconds=60.0,
        )

        async def scenario() -> None:
            await scheduler.start()
            await scheduler.attach("margaret", uuid4())
            orchestrator.failure = None
            await scheduler.attach("margaret", uuid4())
            await scheduler.stop()

        asyncio.run(scenario())

        self.assertEqual(orchestrator.calls, 2)
        self.assertFalse(scheduler.running)

    def test_detaching_the_last_subscriber_stops_evaluating_that_participant(self) -> None:
        hub = SessionEventHub()
        orchestrator = _StubOrchestrator([])
        scheduler = ProactiveReminderScheduler(
            orchestrator=orchestrator,
            event_hub=hub,
            scan_interval_seconds=60.0,
        )

        async def scenario() -> None:
            participant = uuid4()
            await scheduler.attach("margaret", participant)
            await scheduler.attach("margaret", participant)
            await scheduler.detach("margaret")
            self.assertEqual(len(scheduler._watchers), 1)  # noqa: SLF001
            await scheduler.detach("margaret")
            self.assertEqual(scheduler._watchers, {})  # noqa: SLF001

        asyncio.run(scenario())

    def test_the_participant_topic_is_separate_from_session_topics(self) -> None:
        hub = SessionEventHub()
        session_id = uuid4()
        session_events: list[dict[str, Any]] = []

        async def scenario() -> None:
            async def listen() -> None:
                async for event in hub.subscribe(session_id):
                    if event.get("type") != "keepalive":
                        session_events.append(event)

            listener = asyncio.create_task(listen())
            await asyncio.sleep(0)
            await hub.publish(user_topic("margaret"), {"type": "proactive_reminder"})
            await asyncio.sleep(0.05)
            listener.cancel()

        asyncio.run(scenario())

        self.assertEqual(session_events, [])


class LapsedRoutineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "operations.sqlite3"
        self.repository = OperationalRepository(str(database_path))
        self.everos = _Everos()
        self.service = ActivityMemoryService(self.repository, self.everos)
        self.participant_id = uuid4()
        self.repository.create_participant(
            participant_id=self.participant_id,
            user_id="margaret",
            role="user",
            participant_name="Margaret",
            preferences={
                "timezone": "America/Los_Angeles",
                "activity_memory_enabled": True,
                "proactive_reminders_enabled": True,
            },
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary_directory.cleanup()

    def _session(self, moment: datetime, task_name: str = "Book haircut") -> SessionView:
        return SessionView(
            id=uuid4(),
            user_id="margaret",
            participant_session_id=self.participant_id,
            mode=SessionMode.REPLAY,
            state=SessionState.CREATED,
            state_version=0,
            task_name=task_name,
            task_intent=task_name,
            start_url="https://salon.example/",
            skill_id="skill-haircut",
            created_at=moment,
            updated_at=moment,
        )

    def _record_monthly_haircuts(self) -> RoutinePattern:
        zone = ZoneInfo("America/Los_Angeles")
        for month in (5, 6, 7):
            moment = datetime(2026, month, 6, 10, 0, tzinfo=zone)
            self.service.record_session_start(self._session(moment.astimezone(UTC)))
        return self.service.patterns("margaret")[0]

    def test_a_lapsed_monthly_routine_is_phrased_as_a_lapse(self) -> None:
        pattern = self._record_monthly_haircuts()
        routine = RoutineSummary(
            id="skill-haircut",
            name="Book haircut",
            start_url="https://salon.example/",
        )

        reminders = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=pattern.next_due_at + timedelta(days=7),
        )

        self.assertEqual(len(reminders), 1)
        self.assertIn("You last did Book haircut about a month ago", reminders[0].reason)
        self.assertIn("Would you like to do it now?", reminders[0].reason)
        self.assertEqual(reminders[0].overdue_days, 7)

    def test_a_routine_due_soon_explains_the_learned_timing(self) -> None:
        pattern = self._record_monthly_haircuts()
        routine = RoutineSummary(
            id="skill-haircut",
            name="Book haircut",
            start_url="https://salon.example/",
        )

        reminders = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=pattern.next_due_at - timedelta(days=1),
        )

        self.assertEqual(len(reminders), 1)
        self.assertIn("usually start Book haircut around 10:00 AM each month", reminders[0].reason)
        self.assertIn("based on 3 times", reminders[0].reason)
        self.assertEqual(reminders[0].overdue_days, 0)

    def test_a_routine_abandoned_for_months_stops_nagging(self) -> None:
        pattern = self._record_monthly_haircuts()
        routine = RoutineSummary(
            id="skill-haircut",
            name="Book haircut",
            start_url="https://salon.example/",
        )

        reminders = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=pattern.next_due_at + timedelta(days=120),
        )

        self.assertEqual(reminders, [])

    def test_a_reworded_provider_routine_still_matches_the_learned_pattern(self) -> None:
        pattern = self._record_monthly_haircuts()
        # EverOS distils skill names, so the confirmed routine rarely repeats the
        # participant's exact task wording.
        routine = RoutineSummary(
            id="skill-haircut",
            name="Book Haircut Appointment",
            start_url="https://salon.example/",
        )

        reminders = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=pattern.next_due_at,
        )

        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].routine.name, "Book Haircut Appointment")

    def test_an_unrelated_routine_is_never_paired_with_a_pattern(self) -> None:
        pattern = self._record_monthly_haircuts()
        routine = RoutineSummary(
            id="skill-water",
            name="Pay water bill",
            start_url="https://billing.example/",
        )

        reminders = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=pattern.next_due_at,
        )

        self.assertEqual(reminders, [])

    def test_a_learned_pattern_is_written_to_everos_foresight_memory(self) -> None:
        self._record_monthly_haircuts()
        session = self._session(datetime(2026, 7, 6, 17, tzinfo=UTC))
        self.service.record_session_start(session)
        self.service.record_outcome(session, "completed")

        asyncio.run(self.service.sync_session_summary(session))

        self.assertEqual(len(self.everos.foresight_writes), 1)
        write = self.everos.foresight_writes[0]
        self.assertEqual(write["user_id"], "margaret")
        self.assertEqual(write["pattern"]["recurrence"], "monthly")
        self.assertIsNotNone(write["last_completed_at"])


if __name__ == "__main__":
    unittest.main()
