from __future__ import annotations

import hashlib
import logging
import re
import statistics
from calendar import monthrange
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final
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

logger = logging.getLogger(__name__)

_INTERVALS: Final = {
    RecurrenceKind.DAILY: timedelta(days=1),
    RecurrenceKind.WEEKLY: timedelta(days=7),
    RecurrenceKind.MONTHLY: timedelta(days=30),
}
_LEADS: Final = {
    RecurrenceKind.DAILY: timedelta(hours=2),
    RecurrenceKind.WEEKLY: timedelta(hours=24),
    RecurrenceKind.MONTHLY: timedelta(days=3),
}
# How far past the expected time a routine has to slip before the suggestion is
# phrased as a lapse ("you last did this a month ago") instead of a due-soon nudge.
_LAPSED_AFTER: Final = {
    RecurrenceKind.DAILY: timedelta(hours=12),
    RecurrenceKind.WEEKLY: timedelta(days=2),
    RecurrenceKind.MONTHLY: timedelta(days=5),
}
_WORD: Final = re.compile(r"[a-z0-9]+")
_GENERIC_TASK_WORDS: Final = frozenset(
    {"the", "a", "an", "my", "for", "and", "of", "to", "with", "on", "at", "in", "online"}
)


def _significant_terms(text: str) -> set[str]:
    return {
        word
        for word in _WORD.findall(text.casefold())
        if word not in _GENERIC_TASK_WORDS and len(word) > 2
    }


def _spoken_gap(delta: timedelta) -> str:
    days = max(delta.days, 0)
    if days <= 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 45:
        return "about a month ago"
    if days < 340:
        return f"about {max(round(days / 30), 2)} months ago"
    return "over a year ago"


class ActivityMemoryService:
    """Consent-gated activity capture, deterministic pattern inference, and EverOS summaries."""

    def __init__(
        self,
        repository: OperationalRepository,
        everos: Any,
        *,
        max_overdue_intervals: float = 3.0,
    ) -> None:
        self.repository = repository
        self.everos = everos
        self.max_overdue_intervals = max_overdue_intervals

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
        if matching_pattern is not None:
            await self._sync_foresight(session.user_id, matching_pattern, summary)

    async def _sync_foresight(
        self,
        user_id: str,
        pattern: RoutinePattern,
        summary: Mapping[str, Any],
    ) -> None:
        """Persist the inferred timing as EverOS `foresight` memory.

        The pattern is inferred locally and deterministically, but the product's proactive
        nudges are documented as EverOS foresight memory, so the same statement has to
        exist there for the caregiver-readable record and for cross-device recall.
        """

        save = getattr(self.everos, "save_foresight", None)
        if save is None:
            return
        try:
            await save(
                user_id,
                pattern.model_dump(mode="json"),
                last_completed_at=str(summary.get("ended_at") or "") or None,
            )
        except Exception:
            # Foresight is an enrichment of an already-persisted episode. Losing it must
            # not fail the completion path or retract the activity sync that succeeded.
            logger.warning(
                "Could not store the inferred timing pattern for task %s in EverOS foresight "
                "memory; the local pattern remains authoritative.",
                pattern.task_id,
            )

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
        reminders: list[ProactiveReminder] = []
        for pattern in self.patterns(user_id):
            routine = self._match_routine(pattern, routines)
            if routine is None:
                continue
            interval = _INTERVALS[pattern.recurrence]
            lead = _LEADS[pattern.recurrence]
            if current < pattern.next_due_at - lead:
                continue
            overdue = current - pattern.next_due_at
            # A routine that slipped several whole cycles is no longer a timely nudge, and
            # repeating it forever would be the nagging the interaction model forbids.
            if overdue > interval * self.max_overdue_intervals:
                continue
            reminder_id = self._reminder_id(user_id, pattern)
            action = self.repository.get_reminder_action(reminder_id, user_id)
            if action:
                if action["status"] == "accepted":
                    continue
                snoozed_until = action.get("snoozed_until")
                if snoozed_until and current < datetime.fromisoformat(str(snoozed_until)):
                    continue
            reminders.append(
                ProactiveReminder(
                    id=reminder_id,
                    routine=routine,
                    reason=self._reason(pattern, overdue),
                    due_at=pattern.next_due_at,
                    pattern=pattern,
                    overdue_days=max(overdue.days, 0),
                    can_start_guidance=True,
                )
            )
        return reminders

    def _reason(self, pattern: RoutinePattern, overdue: timedelta) -> str:
        """Phrase one calm suggestion that says why it appeared."""

        local_due = pattern.next_due_at.astimezone(self._zone(pattern.timezone))
        local_time = f"{int(local_due.strftime('%I'))}:{local_due.strftime('%M %p')}"
        cadence = {
            RecurrenceKind.DAILY: "each day",
            RecurrenceKind.WEEKLY: "each week",
            RecurrenceKind.MONTHLY: "each month",
        }[pattern.recurrence]
        if overdue >= _LAPSED_AFTER[pattern.recurrence]:
            elapsed = _spoken_gap(overdue + _INTERVALS[pattern.recurrence])
            reason = (
                f"You last did {pattern.task_name} {elapsed}, and you usually do it "
                f"{cadence}. Would you like to do it now?"
            )
        else:
            reason = (
                f"You usually start {pattern.task_name} around {local_time} {cadence}, "
                f"based on {pattern.occurrence_count} times I have seen. "
                "Would you like to start it?"
            )
        return reason[:240]

    def _match_routine(
        self,
        pattern: RoutinePattern,
        routines: Sequence[RoutineSummary],
    ) -> RoutineSummary | None:
        """Pair an inferred pattern with a confirmed routine.

        The pattern's task id is a hash of the task name observed locally, while the
        routine name comes back from EverOS skill distillation, which rewords it. Exact
        hashing alone therefore silently dropped reminders, so name normalization and then
        token overlap are tried before giving up.
        """

        for routine in routines:
            if self._task_id(routine.name) == pattern.task_id:
                return routine
        wanted = _significant_terms(pattern.task_name)
        if not wanted:
            return None
        best: RoutineSummary | None = None
        best_score = 0.0
        for routine in routines:
            available = _significant_terms(routine.name)
            if not available:
                continue
            shared = wanted & available
            if not shared:
                continue
            score = len(shared) / len(wanted | available)
            if score > best_score:
                best_score = score
                best = routine
        return best if best_score >= 0.5 else None

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
