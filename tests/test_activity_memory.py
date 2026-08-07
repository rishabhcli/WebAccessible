from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from backend.app.contracts.models import (
    ParticipantSessionRequest,
    RecurrenceKind,
    RoutineSummary,
    SessionMode,
    SessionState,
    SessionView,
)
from backend.app.persistence.repository import OperationalRepository
from backend.app.services.activity_memory import ActivityMemoryService


class _MemoryAdapter:
    async def save_activity_memory(self, *_args: object, **_kwargs: object) -> dict[str, str]:
        return {"status": "accepted"}


class ActivityMemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "operations.sqlite3"
        self.repository = OperationalRepository(str(database_path))
        self.service = ActivityMemoryService(self.repository, _MemoryAdapter())
        self.participant_id = uuid4()

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary_directory.cleanup()

    def _participant(self, *, memory: bool, reminders: bool) -> None:
        self.repository.create_participant(
            participant_id=self.participant_id,
            user_id="margaret",
            role="user",
            participant_name="Margaret",
            preferences={
                "timezone": "America/Los_Angeles",
                "activity_memory_enabled": memory,
                "proactive_reminders_enabled": reminders,
            },
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    def _session(self, created_at: datetime, task_name: str = "Pay water bill") -> SessionView:
        return SessionView(
            id=uuid4(),
            user_id="margaret",
            participant_session_id=self.participant_id,
            mode=SessionMode.REPLAY,
            state=SessionState.CREATED,
            state_version=0,
            task_name=task_name,
            task_intent=task_name,
            start_url="https://billing.example/",
            skill_id="skill-water",
            created_at=created_at,
            updated_at=created_at,
        )

    def test_activity_is_not_recorded_without_explicit_permission(self) -> None:
        self._participant(memory=False, reminders=False)

        self.service.record_session_start(self._session(datetime(2026, 7, 3, 16, tzinfo=UTC)))

        self.assertEqual(self.repository.list_activities("margaret"), [])

    def test_weekly_pattern_produces_a_permission_gated_reminder(self) -> None:
        self._participant(memory=True, reminders=True)
        zone = ZoneInfo("America/Los_Angeles")
        for day in (3, 10, 17):
            local_time = datetime(2026, 7, day, 9, 0, tzinfo=zone)
            self.service.record_session_start(self._session(local_time.astimezone(UTC)))

        patterns = self.service.patterns("margaret")

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].recurrence, RecurrenceKind.WEEKLY)
        self.assertEqual(patterns[0].typical_local_time, "09:00")
        routine = RoutineSummary(
            id="skill-water",
            name="Pay water bill",
            start_url="https://billing.example/",
        )
        reminders = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=patterns[0].next_due_at - timedelta(minutes=30),
        )

        self.assertEqual(len(reminders), 1)
        self.assertTrue(reminders[0].permission_required)
        self.assertIn("usually start Pay water bill", reminders[0].reason)

    def test_dismissed_reminder_is_snoozed(self) -> None:
        self._participant(memory=True, reminders=True)
        zone = ZoneInfo("America/Los_Angeles")
        for day in (3, 10):
            local_time = datetime(2026, 7, day, 9, 0, tzinfo=zone)
            self.service.record_session_start(self._session(local_time.astimezone(UTC)))
        routine = RoutineSummary(
            id="skill-water",
            name="Pay water bill",
            start_url="https://billing.example/",
        )
        due_at = self.service.patterns("margaret")[0].next_due_at
        reminder = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=due_at,
        )[0]
        self.repository.record_reminder_action(
            reminder_id=reminder.id,
            user_id="margaret",
            task_id=reminder.pattern.task_id,
            status="dismissed",
            acted_at=due_at,
            snoozed_until=due_at + timedelta(days=1),
        )

        reminders = self.service.reminders(
            user_id="margaret",
            participant_session_id=self.participant_id,
            routines=[routine],
            now=due_at + timedelta(hours=1),
        )

        self.assertEqual(reminders, [])

    def test_retries_on_the_same_day_do_not_create_a_pattern(self) -> None:
        self._participant(memory=True, reminders=True)
        zone = ZoneInfo("America/Los_Angeles")
        self.service.record_session_start(
            self._session(datetime(2026, 7, 3, 9, 0, tzinfo=zone).astimezone(UTC))
        )
        self.service.record_session_start(
            self._session(datetime(2026, 7, 3, 10, 0, tzinfo=zone).astimezone(UTC))
        )

        self.assertEqual(self.service.patterns("margaret"), [])

    def test_monthly_pattern_stays_on_the_usual_day_of_month(self) -> None:
        self._participant(memory=True, reminders=True)
        zone = ZoneInfo("America/Los_Angeles")
        for month in (6, 7, 8):
            local_time = datetime(2026, month, 6, 9, 0, tzinfo=zone)
            self.service.record_session_start(self._session(local_time.astimezone(UTC)))

        pattern = self.service.patterns("margaret")[0]

        self.assertEqual(pattern.recurrence, RecurrenceKind.MONTHLY)
        self.assertEqual(pattern.next_due_at.astimezone(zone).day, 6)

    def test_reminder_permission_cannot_be_enabled_without_memory(self) -> None:
        with self.assertRaises(ValidationError):
            ParticipantSessionRequest(
                user_id="margaret",
                participant_name="Margaret",
                activity_memory_enabled=False,
                proactive_reminders_enabled=True,
            )


if __name__ == "__main__":
    unittest.main()
