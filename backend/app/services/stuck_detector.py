from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from backend.app.contracts.models import EventEnvelope, EventType


class StuckReason(StrEnum):
    IDLE = "idle"
    URL_LOOP = "url_loop"
    SCROLL_LOOP = "scroll_loop"
    ROUTE_DEPARTURE = "route_departure"
    PARTIAL_FORM_IDLE = "partial_form_idle"
    UNKNOWN_SENSITIVE_REQUEST = "unknown_sensitive_request"
    EXPLICIT_HELP = "explicit_help"


@dataclass
class ObservationWindow:
    last_productive_at: datetime
    page_key: str
    known_task: bool = False
    partly_filled_at: datetime | None = None
    visits: dict[str, deque[datetime]] = field(default_factory=lambda: defaultdict(deque))
    scrolls: deque[tuple[datetime, float]] = field(default_factory=deque)
    offered: bool = False


class StuckDetector:
    def __init__(self) -> None:
        self._windows: dict[UUID, ObservationWindow] = {}

    def observe(
        self,
        event: EventEnvelope,
        *,
        known_task: bool,
        known_site: bool,
        now: datetime | None = None,
    ) -> StuckReason | None:
        current = now or datetime.now(UTC)
        page_key = self.page_key(event.origin, event.redacted_path)
        window = self._windows.setdefault(
            event.session_id,
            ObservationWindow(last_productive_at=current, page_key=page_key, known_task=known_task),
        )

        if event.event_type == EventType.HELP_REQUESTED:
            return StuckReason.EXPLICIT_HELP

        if event.event_type == EventType.NAVIGATION_OBSERVED:
            window.page_key = page_key
            visits = window.visits[page_key]
            visits.append(current)
            self._trim(visits, current - timedelta(minutes=2))
            window.last_productive_at = current
            if len(visits) >= 3:
                return StuckReason.URL_LOOP
            if event.payload.get("known_route_departure") is True:
                return StuckReason.ROUTE_DEPARTURE

        if event.event_type == EventType.FORM_PROGRESS_OBSERVED:
            if event.payload.get("partly_filled") is True:
                window.partly_filled_at = current
            if event.payload.get("sensitive") is True and not known_site:
                return StuckReason.UNKNOWN_SENSITIVE_REQUEST

        if event.event_type in {
            EventType.USER_ACTION_OBSERVED,
            EventType.VERIFICATION_OBSERVED,
        } or (
            event.event_type == EventType.INTERACTION_OBSERVED and event.payload.get("productive")
        ):
            window.last_productive_at = current
            window.scrolls.clear()
            if event.event_type == EventType.VERIFICATION_OBSERVED and event.payload.get(
                "verified"
            ):
                window.partly_filled_at = None

        if (
            event.event_type == EventType.INTERACTION_OBSERVED
            and event.payload.get("kind") == "scroll"
        ):
            delta = abs(float(event.payload.get("viewport_delta", 0)))
            window.scrolls.append((current, delta))
            while window.scrolls and window.scrolls[0][0] < current - timedelta(seconds=20):
                window.scrolls.popleft()
            if len(window.scrolls) >= 4 and sum(item[1] for item in window.scrolls) >= 3:
                return StuckReason.SCROLL_LOOP

        if window.partly_filled_at and current - window.partly_filled_at >= timedelta(seconds=40):
            return StuckReason.PARTIAL_FORM_IDLE

        idle_seconds = 45 if known_task else 60
        if current - window.last_productive_at >= timedelta(seconds=idle_seconds):
            return StuckReason.IDLE
        return None

    def clear_offer(self, session_id: UUID) -> None:
        if session_id in self._windows:
            self._windows[session_id].offered = False

    @staticmethod
    def page_key(origin: str, path: str) -> str:
        parsed = urlsplit(origin)
        normalized = "/" + "/".join(part for part in path.split("/") if part)
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{normalized}".rstrip("/") or "/"

    @staticmethod
    def _trim(values: deque[datetime], cutoff: datetime) -> None:
        while values and values[0] < cutoff:
            values.popleft()
