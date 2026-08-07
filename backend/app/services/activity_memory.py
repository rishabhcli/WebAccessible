from __future__ import annotations

import hashlib
import statistics
from calendar import monthrange
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.contracts.models import (
    EventEnvelope,
    ProactiveReminder,
    RecurrenceKind,
    RoutinePattern,
    RoutineSummary,
    SessionView,
)
from backend.app.persistence.repository import OperationalRepository


class ActivityMemoryService:
    """Consent-gated activity capture, deterministic pattern inference, and EverOS summaries."""

    def __init__(self, repository: OperationalRepository, everos: Any) -> None:
        self.repository = repository
        self.everos = everos

    def consent(self, participant_session_id: UUID | str) -> tuple[bool, bool, str]:
        participant = self.repository.get_participant(participant_session_id)
        if participant is None:
            return False, False, "UTC"
        preferences = participant.get("preferences") or {}
        memory_enabled = preferences.get("activity_memory_enabled") is True
        reminders_enabled = preferences.get("proactive_reminders_enabled") is True
        timezone = str(preferences.get("timezone") or "UTC")
        return memory_enabled, reminders_enabled and memory_enabled, timezone

    def record_session_start(self, session: SessionView) -> None:
        memory_enabled, _, timezone = self.consent(session.participant_session_id)
        if not memory_enabled:
            return
        self._record(
            activity_id=f"session:{session.id}:started",
            session=session,
            activity_type="task_started",
            occurred_at=session.created_at,
            timezone=timezone,
            origin=self._safe_origin(session.start_url),
        )

    def record_event(self, session: SessionView, event: EventEnvelope) -> None:
        memory_enabled, _, timezone = self.consent(session.participant_session_id)
        if not memory_enabled:
            return
        self._record(
            activity_id=f"event:{event.event_id}",
            session=session,
            activity_type=event.event_type.value,
            occurred_at=event.occurred_at,
            timezone=timezone,
            origin=self._safe_origin(event.origin),
        )

    def record_outcome(self, session: SessionView, outcome: str) -> None:
        memory_enabled, _, timezone = self.consent(session.participant_session_id)
        if not memory_enabled:
            return
        self._record(
            activity_id=f"session:{session.id}:outcome:{outcome}",
            session=session,
            activity_type="task_outcome",
            occurred_at=datetime.now(UTC),
            timezone=timezone,
            origin=self._safe_origin(session.start_url),
            outcome=outcome,
        )

    async def sync_session_summary(self, session: SessionView) -> None:
        memory_enabled, _, _ = self.consent(session.participant_session_id)
        if not memory_enabled:
            return
        summary = self.repository.summarize_session_activity(session.id)
        if summary is None:
            return
        patterns = self.patterns(session.user_id)
        matching_pattern = next(
            (
                pattern
                for pattern in patterns
                if pattern.task_id == self._task_id(session.task_name)
            ),
            None,
        )
        try:
            await self.everos.save_activity_memory(
                session.user_id,
                str(session.id),
                summary,
                matching_pattern.model_dump(mode="json") if matching_pattern else None,
            )
        except Exception:
            self.repository.mark_session_activity_synced(session.id, synced=False)
            return
        self.repository.mark_session_activity_synced(session.id, synced=True)

    def patterns(self, user_id: str) -> list[RoutinePattern]:
        starts = self.repository.list_activities(user_id, activity_type="task_started")
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for start in starts:
            grouped[str(start["task_id"])].append(start)

        patterns: list[RoutinePattern] = []
        for task_id, items in grouped.items():
            distinct_days: dict[str, dict[str, Any]] = {}
            for item in items:
                moment = datetime.fromisoformat(str(item["occurred_at"]))
                timezone_name = str(item["timezone"])
                local_day = moment.astimezone(self._zone(timezone_name)).date().isoformat()
                distinct_days.setdefault(local_day, item)
            items = list(distinct_days.values())
            if len(items) < 2:
                continue
            items.sort(key=lambda item: str(item["occurred_at"]))
            moments = [datetime.fromisoformat(str(item["occurred_at"])) for item in items]
            gaps = [
                max((right - left).total_seconds() / 86400, 0.01)
                for left, right in zip(moments, moments[1:], strict=False)
            ]
            median_gap = statistics.median(gaps)
            if median_gap <= 2:
                recurrence = RecurrenceKind.DAILY
                interval_days = max(1, round(median_gap))
            elif 5 <= median_gap <= 10:
                recurrence = RecurrenceKind.WEEKLY
                interval_days = max(7, round(median_gap))
            elif 24 <= median_gap <= 38:
                recurrence = RecurrenceKind.MONTHLY
                interval_days = round(median_gap)
            else:
                continue

            timezone_name = str(items[-1]["timezone"])
            zone = self._zone(timezone_name)
            typical_minute = round(statistics.median(int(item["local_minute"]) for item in items))
            typical_hour, minute = divmod(typical_minute, 60)
            last_local = moments[-1].astimezone(zone)
            if recurrence == RecurrenceKind.MONTHLY:
                typical_day = round(
                    statistics.median(moment.astimezone(zone).day for moment in moments)
                )
                next_month = 1 if last_local.month == 12 else last_local.month + 1
                next_year = last_local.year + 1 if next_month == 1 else last_local.year
                next_day = min(typical_day, monthrange(next_year, next_month)[1])
                next_date = last_local.date().replace(
                    year=next_year,
                    month=next_month,
                    day=next_day,
                )
            else:
                next_date = last_local.date() + timedelta(days=interval_days)
            next_due = datetime(
                next_date.year,
                next_date.month,
                next_date.day,
                typical_hour % 24,
                minute,
                tzinfo=zone,
            )
            regularity = 1.0
            if len(gaps) > 1 and median_gap:
                regularity = max(0.0, 1.0 - statistics.pstdev(gaps) / median_gap)
            confidence = min(0.98, 0.55 + min(len(items) - 2, 4) * 0.07 + regularity * 0.15)
            patterns.append(
                RoutinePattern(
                    task_id=task_id,
                    task_name=str(items[-1]["task_name"]),
                    recurrence=recurrence,
                    occurrence_count=len(items),
                    typical_local_time=f"{typical_hour % 24:02d}:{minute:02d}",
                    timezone=timezone_name,
                    next_due_at=next_due.astimezone(UTC),
                    confidence=round(confidence, 3),
                )
            )
        return sorted(patterns, key=lambda pattern: pattern.next_due_at)

    def reminders(
        self,
        *,
        user_id: str,
        participant_session_id: UUID | str,
        routines: Sequence[RoutineSummary],
        now: datetime | None = None,
    ) -> list[ProactiveReminder]:
        memory_enabled, reminders_enabled, _ = self.consent(participant_session_id)
        if not memory_enabled or not reminders_enabled:
            return []
        current = (now or datetime.now(UTC)).astimezone(UTC)
        by_task = {self._task_id(routine.name): routine for routine in routines}
        reminders: list[ProactiveReminder] = []
        for pattern in self.patterns(user_id):
            routine = by_task.get(pattern.task_id)
            if routine is None:
                continue
            lead = {
                RecurrenceKind.DAILY: timedelta(hours=2),
                RecurrenceKind.WEEKLY: timedelta(hours=24),
                RecurrenceKind.MONTHLY: timedelta(days=3),
            }[pattern.recurrence]
            if current < pattern.next_due_at - lead:
                continue
            reminder_id = self._reminder_id(user_id, pattern)
            action = self.repository.get_reminder_action(reminder_id, user_id)
            if action:
                if action["status"] == "accepted":
                    continue
                snoozed_until = action.get("snoozed_until")
                if snoozed_until and current < datetime.fromisoformat(str(snoozed_until)):
                    continue
            local_due = pattern.next_due_at.astimezone(self._zone(pattern.timezone))
            local_time = f"{int(local_due.strftime('%I'))}:{local_due.strftime('%M %p')}"
            reason = (
                f"You usually start {pattern.task_name} around {local_time} "
                f"{pattern.recurrence.value}; would you like to start it?"
            )
            reminders.append(
                ProactiveReminder(
                    id=reminder_id,
                    routine=routine,
                    reason=reason,
                    due_at=pattern.next_due_at,
                    pattern=pattern,
                    can_start_guidance=True,
                )
            )
        return reminders

    @staticmethod
    def _task_id(task_name: str) -> str:
        normalized = " ".join(task_name.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _reminder_id(user_id: str, pattern: RoutinePattern) -> str:
        value = f"{user_id}:{pattern.task_id}:{pattern.next_due_at.isoformat()}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _safe_origin(url: str) -> str | None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    @staticmethod
    def _zone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _record(
        self,
        *,
        activity_id: str,
        session: SessionView,
        activity_type: str,
        occurred_at: datetime,
        timezone: str,
        origin: str | None,
        outcome: str | None = None,
    ) -> None:
        moment = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        local = moment.astimezone(self._zone(timezone))
        self.repository.record_activity(
            activity_id=activity_id,
            user_id=session.user_id,
            session_id=session.id,
            task_id=self._task_id(session.task_name),
            task_name=session.task_name,
            activity_type=activity_type,
            occurred_at=moment,
            timezone=timezone,
            local_weekday=local.weekday(),
            local_minute=local.hour * 60 + local.minute,
            origin=origin,
            outcome=outcome,
        )
