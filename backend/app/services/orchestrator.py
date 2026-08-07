from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from backend.app.browser.controller import BrowserController, ProviderBlockedSite
from backend.app.contracts.models import (
    BackendCommand,
    CommandType,
    ElementCandidate,
    EpisodeAnswer,
    EventBatchAck,
    EventBatchRequest,
    EventEnvelope,
    EventType,
    GuidanceDecision,
    GuidanceMode,
    ProactiveReminder,
    RoutineSummary,
    SelectorBundle,
    SelectorSpec,
    SelectorType,
    SessionMode,
    SessionState,
    SessionView,
    SkillDocument,
    SkillOutcome,
    SkillStep,
    SyncState,
    TargetCommand,
    TaskResolveResponse,
    VerificationPredicate,
    VerificationType,
)
from backend.app.domain.demos import DEMO_TASKS
from backend.app.domain.safety import SafetyPolicy
from backend.app.domain.sessions import ensure_transition
from backend.app.domain.skills import parse_skill_markdown, provider_value
from backend.app.persistence.repository import OperationalRepository
from backend.app.services.activity_memory import ActivityMemoryService
from backend.app.services.completion import CompletionService
from backend.app.services.event_hub import SessionEventHub
from backend.app.services.guidance import GuidanceResult, GuidanceService
from backend.app.services.recall import RecallService
from backend.app.services.repair import RepairService
from backend.app.services.replay import ReplayEngine
from backend.app.services.route_recorder import RouteRecorder
from backend.app.services.stuck_detector import StuckDetector, StuckReason

logger = logging.getLogger(__name__)

_FILLER_WORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "my", "our", "your", "for", "and", "or", "of", "to", "with",
        "on", "at", "in", "get", "got", "please", "want", "need", "book", "make", "do",
        "line", "online", "new", "next", "some", "from", "into", "that", "this",
    }
)


def _content_words(text: str) -> set[str]:
    """Return the words in a phrase that actually carry the topic."""

    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.casefold())
        if len(word) > 2 and word not in _FILLER_WORDS
    }



@dataclass
class ActiveStep:
    command: BackendCommand
    candidate: ElementCandidate
    decision: GuidanceDecision | None
    mode: GuidanceMode


class SessionOrchestrator:
    def __init__(
        self,
        *,
        repository: OperationalRepository,
        browser: BrowserController,
        everos: Any,
        guidance: GuidanceService,
        completion: CompletionService,
        event_hub: SessionEventHub,
        demo_target_name: str,
        demo_target_url: str,
        demo_fallback_url: str,
        build_commit: str,
        source_environment: str,
        recall: RecallService | None = None,
        routine_cache_seconds: float = 20.0,
        max_overdue_intervals: float = 3.0,
        embedder: Any = None,
        embedding_model: str | None = None,
    ) -> None:
        self.repository = repository
        self.browser = browser
        self.everos = everos
        self.guidance = guidance
        self.completion = completion
        self.event_hub = event_hub
        self.demo_target_name = demo_target_name
        self.demo_target_url = demo_target_url
        self.demo_fallback_url = demo_fallback_url
        self.build_commit = build_commit
        self.source_environment = source_environment
        self.recall = recall
        self.routine_cache_seconds = routine_cache_seconds
        self.embedder = embedder
        self.embedding_model = embedding_model
        self.stuck = StuckDetector()
        self.route_recorder = RouteRecorder(repository)
        self.replay = ReplayEngine()
        self.repair = RepairService()
        self.safety_policy = SafetyPolicy()
        self.activity_memory = ActivityMemoryService(
            repository,
            everos,
            max_overdue_intervals=max_overdue_intervals,
        )
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._active: dict[UUID, ActiveStep] = {}
        self._skills: dict[UUID, SkillDocument] = {}
        self._commands: dict[UUID, BackendCommand] = {}
        self._pending_selector_attempts: dict[UUID, str] = {}
        self._routine_cache: dict[str, tuple[float, list[RoutineSummary]]] = {}
        self._routine_locks: dict[str, asyncio.Lock] = {}

    def create_session(
        self,
        *,
        user_id: str,
        participant_session_id: UUID,
        mode: SessionMode,
        task_name: str,
        task_intent: str,
        skill_id: str | None,
        start_url: str,
    ) -> SessionView:
        now = datetime.now(UTC)
        session = SessionView(
            id=uuid4(),
            user_id=user_id,
            participant_session_id=participant_session_id,
            mode=mode,
            state=SessionState.CREATED,
            state_version=0,
            task_name=task_name,
            task_intent=task_intent,
            start_url=start_url,
            skill_id=skill_id,
            sync_state=SyncState.PENDING,
            created_at=now,
            updated_at=now,
        )
        self.repository.create_session(session)
        self.activity_memory.record_session_start(session)
        self.repository.enqueue(
            "session_run",
            f"{session.id}:started",
            {
                "run_id": str(session.id),
                "session_id": str(session.id),
                "user_id": user_id,
                "task_id": skill_id or self._stable_task_id(task_name),
                "task_name": task_name,
                "mode": mode.value,
                "skill_id": skill_id,
                "sync_status": "synced",
                "started_at": now.isoformat(),
                "fixture_mode": False,
                "build_commit": self.build_commit,
                "source_environment": self.source_environment,
                "last_synced_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        return session

    async def attach_browser(self, session_id: UUID, start_url: str) -> SessionView:
        async with self._lock(session_id):
            session = self._require_session(session_id)
            if session.state != SessionState.CREATED:
                return session
            try:
                view = await self.browser.start(
                    web_session_id=session.id, user_id=session.user_id, start_url=start_url
                )
            except ProviderBlockedSite:
                updated = self._transition(
                    session,
                    SessionState.PROVIDER_UNAVAILABLE,
                    browser_status="unavailable",
                    terminal_message=(
                        "This site cannot be opened in the browser I use, so nothing started."
                    ),
                )
                await self._publish(updated)
                raise
            except Exception as error:
                # The sanitized message goes to the participant; the cause has to reach the
                # log or a failure to start is undiagnosable from the outside.
                logger.exception("Could not attach a managed browser session.")
                updated = self._transition(
                    session,
                    SessionState.PROVIDER_UNAVAILABLE,
                    browser_status="unavailable",
                    terminal_message="Browserbase could not start this browser session.",
                )
                await self._publish(updated)
                raise RuntimeError("Browserbase session unavailable") from error
            updated = self._transition(
                session,
                SessionState.OBSERVING,
                browserbase_session_id=view.browserbase_session_id,
                browser_status="connected",
            )
            attached_at = datetime.now(UTC)
            self.repository.enqueue(
                "browser_session",
                f"{view.browserbase_session_id}:attached",
                {
                    "browserbase_session_id": view.browserbase_session_id,
                    "session_id": str(session.id),
                    "run_id": str(session.id),
                    "user_id": session.user_id,
                    "provider_status": "connected",
                    "sync_status": "synced",
                    "created_at": view.created_at.isoformat(),
                    "cdp_attached_at": attached_at.isoformat(),
                    "live_view_ready_at": attached_at.isoformat(),
                    "last_provider_check_at": attached_at.isoformat(),
                    "last_synced_at": attached_at.isoformat(),
                    "updated_at": attached_at.isoformat(),
                    "agent_surface_used": False,
                    "source_environment": self.source_environment,
                },
            )
            await self._publish(updated)
        if updated.mode == SessionMode.REPLAY:
            await self.begin_guidance(session_id, reason="replay_started")
        return self._require_session(session_id)

    async def stop_browser(self, session_id: UUID, reason: str) -> bool:
        stopped = await self.browser.stop(session_id, reason)
        session = self._require_session(session_id)
        self.repository.update_session(
            session_id,
            increment_version=False,
            browser_status="stopped" if stopped else "termination_failed",
        )
        if session.browserbase_session_id:
            stopped_at = datetime.now(UTC)
            self.repository.enqueue(
                "browser_session",
                f"{session.browserbase_session_id}:terminated",
                {
                    "browserbase_session_id": session.browserbase_session_id,
                    "session_id": str(session.id),
                    "run_id": str(session.id),
                    "user_id": session.user_id,
                    "provider_status": "terminated" if stopped else "termination_failed",
                    "terminal_reason": reason,
                    "sync_status": "synced",
                    "terminate_requested_at": stopped_at.isoformat(),
                    "terminated_at": stopped_at.isoformat() if stopped else None,
                    "last_provider_check_at": stopped_at.isoformat(),
                    "last_synced_at": stopped_at.isoformat(),
                    "updated_at": stopped_at.isoformat(),
                    "agent_surface_used": False,
                    "source_environment": self.source_environment,
                },
            )
        return stopped

    async def ingest_batch(self, request: EventBatchRequest) -> EventBatchAck:
        accepted: list[UUID] = []
        duplicates: list[UUID] = []
        highest = -1
        for event in sorted(request.events, key=lambda item: item.sequence_no):
            is_new = await self.handle_event(event)
            (accepted if is_new else duplicates).append(event.event_id)
            highest = max(highest, event.sequence_no)
        session = self._require_session(request.events[0].session_id)
        return EventBatchAck(
            accepted_event_ids=accepted,
            duplicate_event_ids=duplicates,
            highest_sequence_no=highest,
            server_state_version=session.state_version,
            session=session,
            command=self._commands.get(session.id),
        )

    async def handle_event(self, event: EventEnvelope) -> bool:
        async with self._lock(event.session_id):
            session = self._require_session(event.session_id)
            if (
                event.user_id != session.user_id
                or event.browserbase_session_id != session.browserbase_session_id
            ):
                raise PermissionError("event is not bound to this participant browser session")
            if not self.repository.append_event(event):
                return False
            self.activity_memory.record_event(session, event)
            self._enqueue_step_telemetry(session, event)
            if event.event_type == EventType.USER_ACTION_OBSERVED:
                self._enqueue_trusted_browser_action(session, event)

            reason = self.stuck.observe(
                event,
                known_task=bool(session.task_name),
                known_site=self._known_origin(event.origin, session),
            )
            if event.event_type == EventType.GUIDANCE_DISMISSED:
                page_key = self.stuck.page_key(event.origin, event.redacted_path)
                self.repository.set_cooldown(session.user_id, page_key, event.occurred_at)
                updated = self._transition(
                    session,
                    SessionState.OBSERVING,
                    current_instruction=None,
                    guidance_mode=GuidanceMode.NONE,
                )
                self._commands.pop(session.id, None)
                await self._publish(updated)
                return True

            if event.event_type == EventType.USER_ACTION_OBSERVED:
                await self._handle_user_action(session, event)
                return True

            if reason == StuckReason.EXPLICIT_HELP:
                asyncio.create_task(self.begin_guidance(session.id, reason=reason.value))
            elif reason and session.state == SessionState.OBSERVING:
                page_key = self.stuck.page_key(event.origin, event.redacted_path)
                dismissed = self.repository.get_cooldown(session.user_id, page_key)
                if dismissed is None or event.occurred_at - dismissed >= timedelta(minutes=10):
                    await self._offer_help(session, reason)
            return True

    async def request_help(self, session_id: UUID) -> SessionView:
        page_id, page_instance_id, origin, path = await self.browser.current_page_identity(
            session_id
        )
        session = self._require_session(session_id)
        if not session.browserbase_session_id:
            raise RuntimeError("browser session has not started")
        sequence = self.repository.highest_sequence(session_id, page_instance_id) + 1
        event = EventEnvelope(
            session_id=session_id,
            user_id=session.user_id,
            browserbase_session_id=session.browserbase_session_id,
            page_id=page_id,
            page_instance_id=page_instance_id,
            sequence_no=sequence,
            origin=origin,
            redacted_path=path,
            event_type=EventType.HELP_REQUESTED,
            payload={"source": "participant_button"},
        )
        await self.handle_event(event)
        await asyncio.sleep(0)
        return self._require_session(session_id)

    async def dismiss_guidance(self, session_id: UUID) -> SessionView:
        page_id, page_instance_id, origin, path = await self.browser.current_page_identity(
            session_id
        )
        session = self._require_session(session_id)
        if not session.browserbase_session_id:
            raise RuntimeError("browser session has not started")
        event = EventEnvelope(
            session_id=session_id,
            user_id=session.user_id,
            browserbase_session_id=session.browserbase_session_id,
            page_id=page_id,
            page_instance_id=page_instance_id,
            sequence_no=self.repository.highest_sequence(session_id, page_instance_id) + 1,
            origin=origin,
            redacted_path=path,
            event_type=EventType.GUIDANCE_DISMISSED,
            payload={"source": "participant_button"},
        )
        await self.handle_event(event)
        await self.browser.clear_highlight(session_id)
        return self._require_session(session_id)

    async def begin_guidance(self, session_id: UUID, *, reason: str) -> SessionView:
        async with self._lock(session_id):
            session = self._require_session(session_id)
            if session.state in {
                SessionState.COMPLETED,
                SessionState.PREPARED,
                SessionState.ESCALATED,
                SessionState.ABANDONED,
                SessionState.FAILED,
            }:
                return session
            candidates = await self.browser.snapshot(session_id)
            _, page_instance_id, current_origin, _ = await self.browser.current_page_identity(
                session_id
            )
            if session.mode == SessionMode.REPLAY:
                try:
                    result = await self._replay_guidance(
                        session, candidates, page_instance_id, current_origin
                    )
                except Exception:
                    result = GuidanceResult(
                        command=BackendCommand(
                            session_id=session.id,
                            server_state_version=session.state_version + 1,
                            command_type=CommandType.PROVIDER_UNAVAILABLE,
                            instruction="Your saved routine is not available right now.",
                        ),
                        decision=None,
                        candidate=None,
                        blocked=True,
                        unavailable_code="everos_skill_unavailable",
                    )
                if result.decision is not None and session.state != SessionState.REPAIRING:
                    session = self._transition(
                        session,
                        SessionState.REPAIRING,
                        repair_attempts=min(session.repair_attempts + 1, 2),
                        current_instruction=(
                            "The page has changed, so I am checking this one step again."
                        ),
                        guidance_mode=GuidanceMode.REPAIR,
                    )
                    await self._publish(session)
            else:
                allowed = [self._origin(self.demo_target_url), self._origin(self.demo_fallback_url)]
                result = await self.guidance.decide(
                    session=session,
                    candidates=candidates,
                    allowed_origins=allowed,
                    current_origin=current_origin,
                    mode=GuidanceMode.COLD,
                    profile=None,
                )
                if result.command.page_instance_id is None:
                    result = GuidanceResult(
                        command=result.command.model_copy(
                            update={"page_instance_id": page_instance_id}
                        ),
                        decision=result.decision,
                        candidate=result.candidate,
                        blocked=result.blocked,
                        should_escalate=result.should_escalate,
                        unavailable_code=result.unavailable_code,
                    )
            return await self._apply_guidance_result(session, result, reason)

    async def list_routines(self, user_id: str) -> list[RoutineSummary]:
        """Return confirmed routines, reusing a recent EverOS read.

        The reminder, dismiss, accept, and task-start paths all need this list, and each
        cold call is a network read. A short cache keeps the interaction immediate while
        staying well inside one participant visit.
        """

        cached = self._cached_routines(user_id)
        if cached is not None:
            return cached
        async with self._routine_lock(user_id):
            cached = self._cached_routines(user_id)
            if cached is not None:
                return cached
            routines: list[RoutineSummary] = []
            try:
                raw = await self._maybe_await(self.everos.list_routines(user_id))
                routines = [
                    item
                    if isinstance(item, RoutineSummary)
                    else RoutineSummary.model_validate(item)
                    for item in (raw or [])
                ]
            except Exception:
                routines = []
            # Offer the curated errands whenever a participant has no confirmed routine
            # for them yet, so a first-time run has somewhere real to start.
            known = {item.start_url for item in routines}
            for demo in DEMO_TASKS:
                if demo.start_url in known:
                    continue
                routines.append(
                    RoutineSummary(
                        id=f"starter:{demo.id}",
                        name=demo.name,
                        description=demo.description,
                        start_url=demo.start_url,
                        source="starter",
                    )
                )
            if self.routine_cache_seconds > 0:
                self._routine_cache[user_id] = (
                    monotonic() + self.routine_cache_seconds,
                    routines,
                )
            return routines

    def invalidate_routines(self, user_id: str) -> None:
        """Drop the cached routine list after skill memory changes."""

        self._routine_cache.pop(user_id, None)

    def _cached_routines(self, user_id: str) -> list[RoutineSummary] | None:
        entry = self._routine_cache.get(user_id)
        if entry is None:
            return None
        expires_at, routines = entry
        if expires_at <= monotonic():
            self._routine_cache.pop(user_id, None)
            return None
        return routines

    def _routine_lock(self, user_id: str) -> asyncio.Lock:
        lock = self._routine_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._routine_locks[user_id] = lock
        return lock

    async def reminders(
        self,
        user_id: str,
        participant_session_id: UUID | str,
    ) -> list[ProactiveReminder]:
        """Return the consented reminders that are currently due for this participant."""

        routines = await self.list_routines(user_id)
        return self.activity_memory.reminders(
            user_id=user_id,
            participant_session_id=participant_session_id,
            routines=routines,
        )

    async def resolve_routines(self, user_id: str, query: str) -> TaskResolveResponse:
        """Match a spoken phrase to confirmed routines.

        Provider skill search runs first. When it returns nothing, the participant's own
        `atomic_fact` vocabulary is used to expand the phrase before local ranking, because
        an older adult's words for a task ("the light bill") rarely match the distilled
        routine name.
        """

        try:
            raw = await self._maybe_await(self.everos.search_routines(user_id, query))
            routines = [
                item if isinstance(item, RoutineSummary) else RoutineSummary.model_validate(item)
                for item in (raw or [])
            ]
        except Exception:
            routines = []
        if not routines:
            all_routines = await self.list_routines(user_id)
            routines = await self._rank_routines(user_id, query, all_routines)
        return TaskResolveResponse(query=query, routines=routines)

    async def _rank_routines(
        self,
        user_id: str,
        query: str,
        routines: Sequence[RoutineSummary],
    ) -> list[RoutineSummary]:
        vocabulary = ""
        resolve_aliases = getattr(self.everos, "resolve_aliases", None)
        if resolve_aliases is not None:
            try:
                aliases = await self._maybe_await(resolve_aliases(user_id, query))
                if isinstance(aliases, list):
                    vocabulary = " ".join(str(alias) for alias in aliases[:6])
            except Exception:
                vocabulary = ""
        # Match on meaningful tokens only. Substring matching on filler words made
        # "the power company" appear to match "Get in line at the DMV", which then
        # suppressed the semantic fallback that would have resolved it correctly.
        words = _content_words(f"{query} {vocabulary}")
        scored = sorted(
            routines,
            key=lambda item: len(words & _content_words(item.name)),
            reverse=True,
        )
        if scored and words & _content_words(scored[0].name):
            return scored[:3]
        semantic = await self._semantic_routines(query, routines)
        return semantic or scored[:3]

    async def _semantic_routines(
        self,
        query: str,
        routines: Sequence[RoutineSummary],
    ) -> list[RoutineSummary]:
        """Rank routines by Cortex embedding similarity when no word matched.

        Word overlap fails on the phrasing this product exists to serve — a participant
        asking for "the light bill" when the routine is named "Pay electric bill". This
        runs only after lexical matching and alias expansion both found nothing, so the
        common path never waits on an embedding call.
        """

        if self.embedder is None or self.embedding_model is None:
            return []
        similarity = getattr(self.embedder, "ai_embed_similarity", None)
        if similarity is None:
            return []
        by_name = {routine.name: routine for routine in routines}
        try:
            ranked = await self._maybe_await(
                similarity(self.embedding_model, query, list(by_name)),
            )
        except Exception:
            logger.warning("Cortex routine similarity was unavailable; keeping word ranking.")
            return []
        if not isinstance(ranked, list):
            return []
        matches: list[RoutineSummary] = []
        for entry in ranked:
            if not isinstance(entry, tuple) or len(entry) != 2:
                continue
            label, score = entry
            routine = by_name.get(str(label))
            if routine is not None and float(score) >= 0.6:
                matches.append(routine)
        return matches[:3]

    async def answer_episode(self, user_id: str, query: str) -> EpisodeAnswer:
        """Answer a spoken recall question from remembered activity."""

        if self.recall is not None:
            try:
                return await self.recall.answer(
                    user_id,
                    query,
                    patterns=self.activity_memory.patterns(user_id),
                )
            except Exception:
                logger.exception("Grounded recall failed; falling back to provider episode read.")
        try:
            raw = await self._maybe_await(self.everos.answer_episode(user_id, query))
            if isinstance(raw, EpisodeAnswer):
                return raw
            if raw:
                return EpisodeAnswer.model_validate(raw)
        except Exception:
            pass
        return EpisodeAnswer(
            found=False,
            answer="I could not find a verified completion memory for that task.",
        )

    async def abandon(self, session_id: UUID, reason: str) -> SessionView:
        async with self._lock(session_id):
            session = self._require_session(session_id)
            if session.state in {SessionState.COMPLETED, SessionState.PREPARED}:
                return session
            updated = self._transition(
                session,
                SessionState.ABANDONED,
                terminal_message="This task was stopped before completion.",
            )
            self._finish_run(updated, "abandoned")
            self.activity_memory.record_outcome(updated, "abandoned")
            await self.activity_memory.sync_session_summary(updated)
            await self._publish(updated)
        await self.stop_browser(session_id, reason)
        return self._require_session(session_id)

    async def _handle_user_action(self, session: SessionView, event: EventEnvelope) -> None:
        candidate_payload = event.payload.get("candidate")
        if not isinstance(candidate_payload, dict):
            return
        candidate = ElementCandidate.model_validate(candidate_payload)
        if (
            session.mode in {SessionMode.CAREGIVER_RECORD, SessionMode.OBSERVE}
            and session.state == SessionState.OBSERVING
        ):
            await self._record_silent_action(session, candidate, event)
            return

        active = self._active.get(session.id)
        if not active or session.state != SessionState.AWAITING_USER_ACTION:
            return
        if candidate.candidate_id != active.candidate.candidate_id:
            self._enqueue_selector_verification(session, event, verified=False)
            rerouting = self._transition(
                session,
                SessionState.REROUTING,
                current_instruction="That's alright - let's find the next step from here.",
            )
            await self._publish(rerouting)
            await self.browser.clear_highlight(session.id)
            asyncio.create_task(self._resume_after_reroute(session.id))
            return

        verifying = self._transition(
            session,
            SessionState.VERIFYING,
            current_instruction="Checking that step now.",
        )
        await self._publish(verifying)
        await self.browser.clear_highlight(session.id)
        await asyncio.sleep(0.45)
        predicate = active.command.expected_transition
        verified = bool(predicate and await self.browser.verify(session.id, predicate))
        self._enqueue_selector_verification(session, event, verified=verified)
        if not verified:
            if session.mode == SessionMode.REPLAY:
                repairing = self._transition(
                    verifying,
                    SessionState.REPAIRING,
                    repair_attempts=min(verifying.repair_attempts + 1, 2),
                    current_instruction=(
                        "The page has changed, so I am checking this one step again."
                    ),
                    guidance_mode=GuidanceMode.REPAIR,
                )
                await self._publish(repairing)
                if repairing.repair_attempts >= 2:
                    await self._escalate(repairing, "two_failed_attempts")
                else:
                    asyncio.create_task(
                        self.begin_guidance(session.id, reason="verification_failed")
                    )
            else:
                rerouting = self._transition(
                    verifying,
                    SessionState.REROUTING,
                    current_instruction=(
                        "That's alright - the page did not change as expected, "
                        "so let's try from here."
                    ),
                )
                await self._publish(rerouting)
                asyncio.create_task(self._resume_after_reroute(session.id))
            return

        if active.mode in {GuidanceMode.COLD, GuidanceMode.REPAIR} and active.decision:
            recorded_step = self.route_recorder.record_verified_step(
                session_id=session.id,
                candidate=candidate,
                instruction=active.decision.instruction,
                css_path=event.payload.get("css_path"),
                verification=active.decision.expected_transition,
                irreversible=False,
            )
            if session.mode == SessionMode.REPLAY and active.mode == GuidanceMode.REPAIR:
                verifying = await self._persist_repair(
                    verifying,
                    recorded_step,
                    reason="selector_or_transition_changed",
                )
        next_index = verifying.current_step_index + 1
        if session.mode == SessionMode.REPLAY:
            skill = self._skills.get(session.id) or await self._load_skill(verifying)
            if next_index >= len(skill.steps):
                await self._finish_replay(verifying, skill, next_index)
                return
        elif await self.completion.completed(session.id):
            await self._complete(verifying)
            return
        observing = self._transition(
            verifying,
            SessionState.OBSERVING,
            current_instruction=None,
            current_step_index=next_index,
        )
        self._active.pop(session.id, None)
        await self._publish(observing)
        asyncio.create_task(self.begin_guidance(session.id, reason="step_verified"))

    async def _record_silent_action(
        self, session: SessionView, candidate: ElementCandidate, event: EventEnvelope
    ) -> None:
        predicate = self._predicate_for_candidate(candidate)
        await asyncio.sleep(0.35)
        verified = await self.browser.verify(session.id, predicate)
        if verified:
            self.route_recorder.record_verified_step(
                session_id=session.id,
                candidate=candidate,
                instruction=(
                    "Choose "
                    f"{candidate.accessible_name or candidate.visible_text or 'this control'}."
                ),
                css_path=event.payload.get("css_path"),
                verification=predicate,
            )
        if await self.completion.completed(session.id):
            await self._complete(session)

    async def _replay_guidance(
        self,
        session: SessionView,
        candidates: list[ElementCandidate],
        page_instance_id: UUID,
        current_origin: str,
    ) -> GuidanceResult:
        skill = await self._load_skill(session)
        resolution = self.replay.resolve(
            skill=skill, step_index=session.current_step_index, candidates=candidates
        )
        if resolution.matched:
            candidate = resolution.candidate
            matched_selector = resolution.matched_selector
            assert candidate is not None
            assert matched_selector is not None
            highlighted = await self.browser.highlight(session.id, candidate.candidate_id)
            if not highlighted:
                resolution = resolution.__class__(
                    resolution.step, None, None, resolution.attempted_tiers
                )
            else:
                selector_attempt_id = (
                    f"{session.id}:{session.current_step_index}:{matched_selector.type.value}"
                )
                command = BackendCommand(
                    session_id=session.id,
                    server_state_version=session.state_version + 1,
                    command_type=CommandType.PRESENT_GUIDANCE,
                    page_instance_id=page_instance_id,
                    instruction=resolution.step.instruction,
                    target=TargetCommand(
                        candidate_id=candidate.candidate_id,
                        selectors=resolution.step.selectors,
                    ),
                    expected_transition=resolution.step.expected_transition,
                )
                self.repository.enqueue(
                    "selector_attempt",
                    selector_attempt_id,
                    {
                        "selector_attempt_id": selector_attempt_id,
                        "session_id": str(session.id),
                        "run_id": str(session.id),
                        "user_id": session.user_id,
                        "step_id": str(resolution.step.step_id),
                        "attempt_no": max(len(resolution.attempted_tiers), 1),
                        "selector_tier": matched_selector.type.value,
                        "selector_fingerprint": self._payload_hash(
                            matched_selector.model_dump(mode="json")
                        ),
                        "resolution_result": "matched",
                        "matched_candidate_count": 1,
                        "verification_predicate": (
                            resolution.step.expected_transition.model_dump_json()
                        ),
                        "verification_result": "pending",
                        "trusted_user_action": False,
                        "replayed_from_memory": True,
                        "model_call_id": None,
                        "source_environment": self.source_environment,
                        "observed_at": datetime.now(UTC).isoformat(),
                    },
                )
                self._pending_selector_attempts[session.id] = selector_attempt_id
                return GuidanceResult(command, None, candidate, blocked=False)

        if session.repair_attempts >= 2:
            return GuidanceResult(
                command=BackendCommand(
                    session_id=session.id,
                    server_state_version=session.state_version + 1,
                    command_type=CommandType.ESCALATED,
                    instruction=(
                        "I could not match this changed page safely, so I have stopped here."
                    ),
                ),
                decision=None,
                candidate=None,
                blocked=True,
                should_escalate=True,
            )
        return await self.guidance.decide(
            session=session,
            candidates=candidates,
            allowed_origins=skill.allowed_origins,
            current_origin=current_origin,
            mode=GuidanceMode.REPAIR,
        )

    async def _apply_guidance_result(
        self, session: SessionView, result: GuidanceResult, reason: str
    ) -> SessionView:
        command = result.command
        self._commands[session.id] = command
        if result.should_escalate:
            return await self._escalate(session, reason)
        if result.command.command_type == CommandType.SAFETY_PAUSE:
            updated = self._transition(
                session,
                SessionState.SAFETY_PAUSED,
                current_instruction=result.command.instruction,
                safety_message=result.command.instruction,
                guidance_mode=GuidanceMode.NONE,
            )
        elif result.command.command_type == CommandType.PROVIDER_UNAVAILABLE:
            updated = self._transition(
                session,
                SessionState.PROVIDER_UNAVAILABLE,
                current_instruction=result.command.instruction,
                guidance_mode=GuidanceMode.NONE,
            )
        elif result.command.command_type == CommandType.ESCALATED:
            return await self._escalate(session, reason)
        else:
            mode = GuidanceMode.REPLAY if session.mode == SessionMode.REPLAY else GuidanceMode.COLD
            if (
                session.state == SessionState.REPAIRING
                or result.decision
                and mode == GuidanceMode.REPLAY
            ):
                mode = GuidanceMode.REPAIR
            guiding = self._transition(
                session,
                SessionState.GUIDING,
                current_instruction=result.command.instruction,
                guidance_mode=mode,
            )
            updated = self._transition(
                guiding,
                SessionState.AWAITING_USER_ACTION,
                increment_version=True,
            )
            command = command.model_copy(update={"server_state_version": updated.state_version})
            self._commands[session.id] = command
            if result.candidate:
                self._active[session.id] = ActiveStep(
                    command=command,
                    candidate=result.candidate,
                    decision=result.decision,
                    mode=mode,
                )
        await self._publish(updated, command)
        return updated

    async def _offer_help(self, session: SessionView, reason: StuckReason) -> None:
        updated = self._transition(
            session,
            SessionState.HELP_OFFERED,
            current_instruction="Would you like help with the next step?",
        )
        command = BackendCommand(
            session_id=session.id,
            server_state_version=updated.state_version,
            command_type=CommandType.OFFER_HELP,
            instruction="Would you like help with the next step?",
        )
        self._commands[session.id] = command
        await self._publish(updated, command, extra={"stuck_reason": reason.value})

    async def _complete(self, session: SessionView) -> None:
        updated = self._transition(
            session,
            SessionState.COMPLETED,
            terminal_message=f"{session.task_name} is complete.",
            current_instruction=f"{session.task_name} is complete.",
            guidance_mode=GuidanceMode.NONE,
        )
        provider_skill_id: str | None = session.skill_id
        provider_receipt: Any = None
        if session.mode != SessionMode.REPLAY:
            try:
                skill = self.route_recorder.compile_skill(
                    session_id=session.id,
                    name=session.task_name,
                    start_url=session.start_url,
                    outcome=SkillOutcome.COMPLETED,
                )
                raw = await self._maybe_await(
                    self.everos.save_teach_run(
                        session.user_id,
                        str(session.id),
                        skill,
                        {
                            "outcome": "completed",
                            "task_name": session.task_name,
                            "occurred_at": datetime.now(UTC).isoformat(),
                            "statement": f"Completed {session.task_name}.",
                        },
                    )
                )
                provider_skill_id = provider_value(raw, "skill_id", "id", default=None)
                provider_receipt = raw
                updated = self.repository.update_session(
                    session.id,
                    increment_version=False,
                    skill_id=provider_skill_id,
                    skill_revision=skill.revision,
                )
                self.repository.enqueue(
                    "skill_revision",
                    f"{skill.skill_key}:{skill.revision}",
                    {
                        "skill_revision_link_id": f"{skill.skill_key}:{skill.revision}",
                        "skill_key": str(skill.skill_key),
                        "revision": skill.revision,
                        "everos_skill_id": provider_skill_id,
                        "source_session_id": str(session.id),
                        "source_run_id": str(session.id),
                        "task_outcome": "completed",
                        "provider_status": "written",
                        "indexing_status": provider_value(
                            raw, "indexing_status", default="unknown"
                        ),
                        "is_current": True,
                        "everos_case_id": provider_value(raw, "case_id", default=None),
                        "source_environment": self.source_environment,
                        "written_at": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception:
                updated = self.repository.update_session(
                    session.id,
                    increment_version=False,
                    sync_state=SyncState.FAILED,
                    terminal_message=(
                        f"{session.task_name} is complete, but its memory is not yet available."
                    ),
                )
        self._finish_run(updated, "completed", provider_receipt=provider_receipt)
        self.activity_memory.record_outcome(updated, "completed")
        await self.activity_memory.sync_session_summary(updated)
        command = BackendCommand(
            session_id=session.id,
            server_state_version=updated.state_version,
            command_type=CommandType.COMPLETED,
            instruction=updated.terminal_message,
        )
        self._commands[session.id] = command
        await self._publish(updated, command)
        asyncio.create_task(self.stop_browser(session.id, "completed"))

    async def _finish_replay(
        self,
        session: SessionView,
        skill: SkillDocument,
        final_step_index: int,
    ) -> None:
        outcome = skill.task_outcome
        state = (
            SessionState.COMPLETED if outcome == SkillOutcome.COMPLETED else SessionState.PREPARED
        )
        message = (
            f"{session.task_name} is complete."
            if outcome == SkillOutcome.COMPLETED
            else f"{session.task_name} is ready for your final confirmation."
        )
        updated = self._transition(
            session,
            state,
            terminal_message=message,
            current_instruction=message,
            current_step_index=final_step_index,
            guidance_mode=GuidanceMode.NONE,
        )
        self._active.pop(session.id, None)
        self._finish_run(updated, outcome.value)
        self.activity_memory.record_outcome(updated, outcome.value)
        await self.activity_memory.sync_session_summary(updated)
        command = BackendCommand(
            session_id=session.id,
            server_state_version=updated.state_version,
            command_type=(
                CommandType.COMPLETED if outcome == SkillOutcome.COMPLETED else CommandType.PREPARED
            ),
            instruction=message,
        )
        self._commands[session.id] = command
        await self._publish(updated, command)
        asyncio.create_task(self.stop_browser(session.id, outcome.value))

    async def _escalate(self, session: SessionView, reason: str) -> SessionView:
        escalation = self.repository.create_escalation(session.id, session.user_id, reason)
        updated = self._transition(
            session,
            SessionState.ESCALATED,
            current_instruction="I have paused here so your caregiver can help with this step.",
            terminal_message="This session is paused for caregiver help.",
            guidance_mode=GuidanceMode.NONE,
        )
        self.repository.enqueue(
            "escalation",
            str(escalation.id),
            {
                "escalation_id": str(escalation.id),
                "session_id": str(session.id),
                "run_id": str(session.id),
                "user_id": session.user_id,
                "reason": reason,
                "status": escalation.status.value,
                "delivery_channel": "caregiver_dashboard",
                "delivery_attempt_count": 0,
                "caregiver_response_status": "awaiting_response",
                "source_environment": self.source_environment,
                "updated_at": escalation.updated_at.isoformat(),
            },
        )
        self._finish_run(updated, "escalated")
        self.activity_memory.record_outcome(updated, "escalated")
        await self.activity_memory.sync_session_summary(updated)
        command = BackendCommand(
            session_id=session.id,
            server_state_version=updated.state_version,
            command_type=CommandType.ESCALATED,
            instruction=updated.current_instruction,
        )
        self._commands[session.id] = command
        await self._publish(updated, command)
        asyncio.create_task(self.stop_browser(session.id, "escalated"))
        return updated

    async def _load_skill(self, session: SessionView) -> SkillDocument:
        cached = self._skills.get(session.id)
        if cached:
            return cached
        if not session.skill_id:
            raise ValueError("replay requires a confirmed EverOS skill")
        raw = await self._maybe_await(self.everos.get_skill(session.user_id, session.skill_id))
        if isinstance(raw, SkillDocument):
            skill = raw
        else:
            content = provider_value(raw, "content", default=None)
            if isinstance(content, str):
                skill = parse_skill_markdown(content)
            elif isinstance(raw, dict):
                skill = SkillDocument.model_validate(raw)
            else:
                raise ValueError("EverOS returned an invalid skill")
        self._skills[session.id] = skill
        self.repository.update_session(
            session.id,
            increment_version=False,
            skill_revision=skill.revision,
            total_steps=len(skill.steps),
        )
        return skill

    async def _persist_repair(
        self,
        session: SessionView,
        replacement: SkillStep,
        *,
        reason: str,
    ) -> SessionView:
        source = await self._load_skill(session)
        repaired = self.repair.revise_one_step(
            skill=source,
            step_index=session.current_step_index,
            replacement=replacement,
            reason=reason,
        )
        provider_status = "repair_not_saved"
        provider_skill_id = session.skill_id
        indexing_status = "unavailable"
        sync_state = SyncState.FAILED
        if not session.skill_id:
            raise ValueError("a replay repair requires its source EverOS skill ID")
        try:
            saved = await self._maybe_await(
                self.everos.save_skill_revision(
                    session.user_id,
                    session.skill_id,
                    repaired,
                    reason,
                )
            )
            if isinstance(saved, SkillDocument):
                repaired = saved
            provider_skill_id = provider_value(
                saved,
                "provider_skill_id",
                "skill_id",
                "id",
                default=session.skill_id,
            )
            provider_status = "written"
            indexing_status = provider_value(saved, "indexing_status", default="ready")
            sync_state = SyncState.SYNCED
        except Exception:
            pass

        self._skills[session.id] = repaired
        updated = self.repository.update_session(
            session.id,
            increment_version=False,
            skill_id=provider_skill_id,
            skill_revision=repaired.revision,
            sync_state=sync_state,
        )
        now = datetime.now(UTC)
        self.repository.enqueue(
            "skill_revision",
            f"{repaired.skill_key}:{repaired.revision}",
            {
                "skill_revision_link_id": f"{repaired.skill_key}:{repaired.revision}",
                "skill_key": str(repaired.skill_key),
                "revision": repaired.revision,
                "everos_skill_id": provider_skill_id if sync_state == SyncState.SYNCED else None,
                "source_session_id": str(session.id),
                "source_run_id": str(session.id),
                "source_step_id": str(replacement.step_id),
                "parent_revision": source.revision,
                "task_outcome": repaired.task_outcome.value,
                "repair_reason": reason,
                "provider_status": provider_status,
                "indexing_status": indexing_status,
                "is_current": sync_state == SyncState.SYNCED,
                "source_environment": self.source_environment,
                "written_at": now.isoformat() if sync_state == SyncState.SYNCED else None,
                "retrieved_at": now.isoformat() if sync_state == SyncState.SYNCED else None,
            },
        )
        return updated

    async def _resume_after_reroute(self, session_id: UUID) -> None:
        await asyncio.sleep(0.6)
        async with self._lock(session_id):
            session = self._require_session(session_id)
            if session.state != SessionState.REROUTING:
                return
            observing = self._transition(session, SessionState.OBSERVING, current_instruction=None)
            await self._publish(observing)
        await self.begin_guidance(session_id, reason="wrong_click")

    def _predicate_for_candidate(self, candidate: ElementCandidate) -> VerificationPredicate:
        selector = SelectorBundle(
            selectors=[
                SelectorSpec(
                    type=SelectorType.ARIA,
                    role=candidate.role or "button",
                    value=candidate.accessible_name
                    or candidate.visible_text
                    or candidate.candidate_id,
                )
            ]
        )
        if candidate.role in {"checkbox", "radio", "switch"} or candidate.input_type in {
            "checkbox",
            "radio",
        }:
            return VerificationPredicate(
                type=VerificationType.ARIA_STATE_EQUALS,
                value="true",
                selector=selector,
                state_name="checked",
            )
        if candidate.href_redacted_path:
            return VerificationPredicate(
                type=VerificationType.URL_PATH_EQUALS, value=candidate.href_redacted_path
            )
        return VerificationPredicate(
            type=VerificationType.ELEMENT_PRESENT, value="target_present", selector=selector
        )

    def _transition(
        self,
        session: SessionView,
        state: SessionState,
        *,
        increment_version: bool = True,
        **changes: Any,
    ) -> SessionView:
        ensure_transition(session.state, state)
        return self.repository.update_session(
            session.id,
            increment_version=increment_version,
            state=state,
            **changes,
        )

    async def _publish(
        self,
        session: SessionView,
        command: BackendCommand | None = None,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "type": "session_state",
            "session": session.model_dump(mode="json"),
            "command": command.model_dump(mode="json") if command else None,
        }
        if extra:
            payload.update(extra)
        await self.event_hub.publish(session.id, payload)

    def _enqueue_step_telemetry(self, session: SessionView, event: EventEnvelope) -> None:
        outcome = "ok"
        if event.event_type == EventType.HELP_REQUESTED:
            outcome = "stuck"
        elif event.payload.get("wrong_click"):
            outcome = "wrong_click"
        synchronized_at = datetime.now(UTC)
        verification_predicate = event.payload.get("verification_predicate")
        payload: dict[str, Any] = {
            "event_id": str(event.event_id),
            "schema_version": event.contract_version,
            "session_id": str(session.id),
            "run_id": str(session.id),
            "user_id": session.user_id,
            "step_no": event.sequence_no,
            "task_id": session.skill_id or self._stable_task_id(session.task_name),
            "step_id": event.payload.get("step_id"),
            "task_name": session.task_name,
            "skill_id": session.skill_id,
            "url_domain": urlsplit(event.origin).netloc,
            "action": event.event_type.value,
            "model_used": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "credits": "0",
            "replayed_from_memory": session.guidance_mode == GuidanceMode.REPLAY,
            "latency_ms": 0,
            "outcome": outcome,
            "guidance_mode": session.guidance_mode.value,
            "sync_attempt": 0,
            "source_environment": self.source_environment,
            "browserbase_session_id": event.browserbase_session_id,
            "page_id": event.page_id,
            "page_instance_id": str(event.page_instance_id),
            "model_call_id": event.payload.get("model_call_id"),
            "selector_tier": event.payload.get("selector_tier"),
            "selector_result": event.payload.get("selector_result"),
            "verification_predicate": (
                json.dumps(verification_predicate, separators=(",", ":"), sort_keys=True)
                if isinstance(verification_predicate, dict | list)
                else verification_predicate
            ),
            "verification_result": event.payload.get("verification_result"),
            "trusted_user_action": event.event_type == EventType.USER_ACTION_OBSERVED,
            "terminal_provenance": event.payload.get("terminal_provenance"),
            "synchronized_at": synchronized_at.isoformat(),
            "ts": event.occurred_at.isoformat(),
        }
        self.repository.enqueue("session_step", str(event.event_id), payload)
        self.repository.enqueue(
            "telemetry_ingestion",
            str(event.event_id),
            {
                "event_id": str(event.event_id),
                "session_id": str(session.id),
                "run_id": str(session.id),
                "user_id": session.user_id,
                "target_table": "SESSION_STEPS",
                "payload_hash": self._payload_hash(payload),
                "source_environment": self.source_environment,
                "status": "synced",
                "attempt_count": 1,
                "first_attempt_at": synchronized_at.isoformat(),
                "last_attempt_at": synchronized_at.isoformat(),
                "synchronized_at": synchronized_at.isoformat(),
                "last_error_code": None,
                "updated_at": synchronized_at.isoformat(),
            },
        )

    def _enqueue_trusted_browser_action(
        self,
        session: SessionView,
        event: EventEnvelope,
    ) -> None:
        if not session.browserbase_session_id:
            return
        occurred_at = event.occurred_at.isoformat()
        self.repository.enqueue(
            "browser_session",
            f"{session.browserbase_session_id}:first-trusted-user-action",
            {
                "browserbase_session_id": session.browserbase_session_id,
                "session_id": str(session.id),
                "run_id": str(session.id),
                "user_id": session.user_id,
                "provider_status": "connected",
                "sync_status": "synced",
                "first_trusted_user_action_at": occurred_at,
                "last_provider_check_at": occurred_at,
                "last_synced_at": occurred_at,
                "updated_at": occurred_at,
                "agent_surface_used": False,
                "source_environment": self.source_environment,
            },
        )

    def _enqueue_selector_verification(
        self,
        session: SessionView,
        event: EventEnvelope,
        *,
        verified: bool,
    ) -> None:
        selector_attempt_id = self._pending_selector_attempts.pop(session.id, None)
        if selector_attempt_id is None:
            return
        self.repository.enqueue(
            "selector_attempt",
            f"{selector_attempt_id}:verification:{event.event_id}",
            {
                "selector_attempt_id": selector_attempt_id,
                "event_id": str(event.event_id),
                "verification_result": "verified" if verified else "failed",
                "trusted_user_action": True,
                "source_environment": self.source_environment,
                "observed_at": event.occurred_at.isoformat(),
            },
        )

    def _finish_run(
        self,
        session: SessionView,
        outcome: str,
        *,
        provider_receipt: Any = None,
    ) -> None:
        finished_at = datetime.now(UTC)
        self.repository.enqueue(
            "session_run",
            f"{session.id}:finished:{outcome}",
            {
                "run_id": str(session.id),
                "session_id": str(session.id),
                "user_id": session.user_id,
                "task_id": session.skill_id or self._stable_task_id(session.task_name),
                "task_name": session.task_name,
                "mode": session.mode.value,
                "skill_id": session.skill_id,
                "skill_revision": session.skill_revision,
                "terminal_outcome": outcome,
                "terminal_provenance": self._terminal_provenance(outcome),
                "verified_amount": session.amount,
                "verified_currency": session.currency,
                "browserbase_session_id": session.browserbase_session_id,
                "everos_case_id": provider_value(provider_receipt, "case_id", default=None),
                "everos_skill_id": session.skill_id,
                "everos_episode_id": provider_value(provider_receipt, "episode_id", default=None),
                "sync_status": "synced",
                "started_at": session.created_at.isoformat(),
                "ended_at": finished_at.isoformat(),
                "fixture_mode": False,
                "build_commit": self.build_commit,
                "source_environment": self.source_environment,
                "last_synced_at": finished_at.isoformat(),
                "updated_at": finished_at.isoformat(),
            },
        )

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _terminal_provenance(outcome: str) -> str:
        if outcome in {"completed", "prepared"}:
            return "deterministic_completion_predicate"
        if outcome == "escalated":
            return "safety_or_repeat_failure"
        return "participant_or_session_stop"

    def _known_origin(self, origin: str, session: SessionView) -> bool:
        known = {self._origin(self.demo_target_url), self._origin(self.demo_fallback_url)}
        skill = self._skills.get(session.id)
        if skill:
            known.update(skill.allowed_origins)
        return self._origin(origin) in known

    def _require_session(self, session_id: UUID) -> SessionView:
        session = self.repository.get_session(session_id)
        if session is None:
            raise KeyError(f"unknown session {session_id}")
        return session

    def _lock(self, session_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        return await value if isawaitable(value) else value

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(str(url))
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    @staticmethod
    def _stable_task_id(task_name: str) -> str:
        return "task:" + "-".join(task_name.casefold().split())[:96]
