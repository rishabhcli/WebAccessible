from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sse_starlette.sse import EventSourceResponse

from backend.app.config import RuntimeMode as ConfigRuntimeMode
from backend.app.contracts.models import (
    CaregiverDashboard,
    EpisodeAnswer,
    EscalationNoteRequest,
    EscalationView,
    EventBatchAck,
    EventBatchRequest,
    HealthResponse,
    ParticipantRole,
    ParticipantSessionRequest,
    ParticipantSessionResponse,
    ProactiveReminder,
    ProviderReadiness,
    ProviderState,
    ReadinessResponse,
    ReminderActionResponse,
    ReminderDismissRequest,
    ReminderListResponse,
    ReviewedBillUploadResponse,
    RoutineSummary,
    RuntimeMode,
    SessionCreateRequest,
    SessionMode,
    SessionView,
    SkillDeleteResponse,
    SkillDocument,
    SkillRevisionRequest,
    TaskEndRequest,
    TaskResolveRequest,
    TaskResolveResponse,
    TaskStartRequest,
)
from backend.app.dependencies import AppContainer
from backend.app.integrations.everos import EverOSErrorCode, EverOSProviderError
from backend.app.services.auth import AuthenticatedParticipant

router = APIRouter()


def container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Participant session required")
    return authorization.removeprefix("Bearer ").strip()


def participant(
    token: Annotated[str, Depends(bearer_token)],
    app: Annotated[AppContainer, Depends(container)],
) -> AuthenticatedParticipant:
    try:
        return app.auth.verify(token)
    except (PermissionError, ValueError) as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


def require_session(
    session_id: UUID, who: AuthenticatedParticipant, app: AppContainer
) -> SessionView:
    session = app.repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != who.user_id:
        raise HTTPException(status_code=403, detail="Session is not available to this participant")
    return session


def require_caregiver(who: AuthenticatedParticipant) -> None:
    if who.role != ParticipantRole.CAREGIVER.value:
        raise HTTPException(status_code=403, detail="Caregiver capability required")


def invalidate_cached_skill(
    app: AppContainer, skill: SkillDocument, provider_skill_id: str
) -> None:
    cached_skills = getattr(app.orchestrator, "_skills", None)
    if not isinstance(cached_skills, dict):
        return
    for session_id, cached in tuple(cached_skills.items()):
        if cached.skill_key == skill.skill_key or cached.provider_skill_id == provider_skill_id:
            cached_skills.pop(session_id, None)


def skill_operation_unavailable(error: Exception, operation: str) -> HTTPException:
    if isinstance(error, EverOSProviderError) and error.code == EverOSErrorCode.UNSUPPORTED:
        return HTTPException(status_code=503, detail=str(error))
    return HTTPException(
        status_code=503,
        detail=f"EverOS could not complete the {operation}; no skill memory was changed.",
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version="0.1.0")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(app: Annotated[AppContainer, Depends(container)]) -> ReadinessResponse:
    settings = app.settings
    browser_active = bool(app.browser._runtimes)  # noqa: SLF001
    browserbase = ProviderReadiness(
        state=(
            ProviderState.AUTHORIZED
            if app.browserbase_authorized
            else ProviderState.CONFIGURED
            if settings.browserbase_configured
            else ProviderState.UNCONFIGURED
        ),
        configured=settings.browserbase_configured,
        reachable=app.browserbase_authorized,
        authorized=app.browserbase_authorized,
        last_checked_at=datetime.now(UTC),
        detail=(
            "A WebAccessible-owned managed browser session is attached."
            if browser_active
            else "Browserbase session listing was authorized during startup reconciliation."
        ),
    )
    try:
        if not settings.everos_configured:
            raise RuntimeError("unconfigured")
        await asyncio.wait_for(app.everos.list_routines("webaccessible-readiness"), timeout=20)
        everos = ProviderReadiness(
            state=ProviderState.AUTHORIZED,
            configured=True,
            reachable=True,
            authorized=True,
            last_checked_at=datetime.now(UTC),
            detail="EverOS memory reads are authorized.",
        )
    except Exception as error:
        everos = ProviderReadiness(
            state=ProviderState.UNCONFIGURED
            if not settings.everos_configured
            else ProviderState.UNAVAILABLE,
            configured=settings.everos_configured,
            last_checked_at=datetime.now(UTC),
            error_code=type(error).__name__,
            detail="EverOS memory is not currently reachable.",
        )
    snowflake = await app.snowflake.readiness()
    model = snowflake.model_copy(
        update={"detail": "Snowflake Cortex guidance follows Snowflake service readiness."}
    )
    capabilities = {
        "browserbase": browserbase,
        "everos": everos,
        "snowflake": snowflake,
        "guidance_model": model,
    }
    return ReadinessResponse(
        mode=RuntimeMode(settings.app_env.value),
        ready=everos.authorized and snowflake.authorized and app.browserbase_authorized,
        fixture_mode=settings.app_env == ConfigRuntimeMode.TEST,
        capabilities=capabilities,
    )


@router.post(
    "/v1/participant-sessions",
    response_model=ParticipantSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_participant_session(
    body: ParticipantSessionRequest,
    app: Annotated[AppContainer, Depends(container)],
) -> ParticipantSessionResponse:
    if app.settings.everos_configured and body.role == ParticipantRole.USER:
        try:
            await app.everos.update_profile(
                body.user_id,
                {
                    "participant_name": body.participant_name,
                    "reading_size": body.reading_size,
                    "voice_enabled": body.voice_enabled,
                    "timezone": body.timezone,
                    "caregiver_mobile": body.caregiver_mobile,
                    "activity_memory_enabled": body.activity_memory_enabled,
                    "proactive_reminders_enabled": body.proactive_reminders_enabled,
                },
            )
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="EverOS could not save the participant setup, so setup was not completed.",
            ) from error
    return app.auth.create(body)


@router.post("/v1/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreateRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SessionView:
    start_url = str(body.start_url or app.settings.demo_target_url)
    allowed = {str(app.settings.demo_target_url), str(app.settings.demo_fallback_url)}
    if start_url not in allowed:
        routines = await app.orchestrator.list_routines(who.user_id)
        if not any(routine.start_url == start_url for routine in routines):
            raise HTTPException(
                status_code=422, detail="The start URL is not part of a confirmed routine"
            )
    if body.mode == SessionMode.REPLAY and not body.skill_id:
        raise HTTPException(status_code=422, detail="Replay requires a confirmed EverOS skill")
    return app.orchestrator.create_session(
        user_id=who.user_id,
        participant_session_id=who.participant_session_id,
        mode=body.mode,
        task_name=body.task_name,
        task_intent=body.task_intent,
        skill_id=body.skill_id,
        start_url=start_url,
    )


@router.get("/v1/sessions/{session_id}", response_model=SessionView)
async def get_session(
    session_id: UUID,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SessionView:
    return require_session(session_id, who, app)


@router.post("/v1/sessions/{session_id}/browser", response_model=SessionView)
async def create_browser(
    session_id: UUID,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SessionView:
    session = require_session(session_id, who, app)
    try:
        return await app.orchestrator.attach_browser(session_id, session.start_url)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/v1/sessions/{session_id}/browser/live-view")
async def live_view(
    session_id: UUID,
    response: Response,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> dict[str, str]:
    require_session(session_id, who, app)
    try:
        url = await app.orchestrator.browser.live_view(session_id)
    except KeyError as error:
        raise HTTPException(status_code=409, detail="Browser session is not attached") from error
    response.headers["Cache-Control"] = "no-store"
    return {"live_view_url": url}


@router.post("/v1/sessions/{session_id}/browser:stop")
async def stop_browser(
    session_id: UUID,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> dict[str, bool]:
    require_session(session_id, who, app)
    return {"stopped": await app.orchestrator.stop_browser(session_id, "participant_stop")}


@router.post("/v1/sessions/{session_id}/events:batch", response_model=EventBatchAck)
async def ingest_events(
    session_id: UUID,
    body: EventBatchRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> EventBatchAck:
    require_session(session_id, who, app)
    if any(event.session_id != session_id or event.user_id != who.user_id for event in body.events):
        raise HTTPException(status_code=403, detail="Event batch is not bound to this session")
    try:
        return await app.orchestrator.ingest_batch(body)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.post("/v1/sessions/{session_id}:help", response_model=SessionView)
async def request_help(
    session_id: UUID,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SessionView:
    require_session(session_id, who, app)
    return await app.orchestrator.request_help(session_id)


@router.post("/v1/sessions/{session_id}:dismiss", response_model=SessionView)
async def dismiss_help(
    session_id: UUID,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SessionView:
    require_session(session_id, who, app)
    return await app.orchestrator.dismiss_guidance(session_id)


@router.get("/v1/sessions/{session_id}/stream")
async def session_stream(
    session_id: UUID,
    request: Request,
    app: Annotated[AppContainer, Depends(container)],
    access_token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> EventSourceResponse:
    token = access_token or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    try:
        who = app.auth.verify(token)
    except (PermissionError, ValueError) as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    require_session(session_id, who, app)

    async def events() -> AsyncIterator[dict[str, str]]:
        yield {
            "event": "session_state",
            "data": require_session(session_id, who, app).model_dump_json(),
        }
        async for event in app.event_hub.subscribe(session_id):
            if await request.is_disconnected():
                break
            yield {
                "event": event.get("type", "message"),
                "data": json.dumps(event, separators=(",", ":"), default=str),
            }

    return EventSourceResponse(events(), headers={"Cache-Control": "no-store"})


@router.get("/v1/routines", response_model=list[RoutineSummary])
async def list_routines(
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> list[RoutineSummary]:
    return await app.orchestrator.list_routines(who.user_id)


@router.get("/v1/reminders", response_model=ReminderListResponse)
async def list_reminders(
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> ReminderListResponse:
    routines = await app.orchestrator.list_routines(who.user_id)
    memory_enabled, reminders_enabled, _ = app.orchestrator.activity_memory.consent(
        who.participant_session_id
    )
    reminders = app.orchestrator.activity_memory.reminders(
        user_id=who.user_id,
        participant_session_id=who.participant_session_id,
        routines=routines,
    )
    return ReminderListResponse(
        reminders=reminders,
        activity_memory_enabled=memory_enabled,
        proactive_reminders_enabled=reminders_enabled,
    )


@router.post("/v1/reminders/{reminder_id}:dismiss", response_model=ReminderActionResponse)
async def dismiss_reminder(
    reminder_id: str,
    body: ReminderDismissRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> ReminderActionResponse:
    reminders = await _current_reminders(who, app)
    reminder = next((item for item in reminders if item.id == reminder_id), None)
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder is no longer active")
    now = datetime.now(UTC)
    app.repository.record_reminder_action(
        reminder_id=reminder.id,
        user_id=who.user_id,
        task_id=reminder.pattern.task_id,
        status="dismissed",
        acted_at=now,
        snoozed_until=now + timedelta(minutes=body.snooze_minutes),
    )
    return ReminderActionResponse(reminder_id=reminder.id, status="dismissed")


@router.post("/v1/reminders/{reminder_id}:accept", response_model=ReminderActionResponse)
async def accept_reminder(
    reminder_id: str,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> ReminderActionResponse:
    reminders = await _current_reminders(who, app)
    reminder = next((item for item in reminders if item.id == reminder_id), None)
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder is no longer active")
    routine = reminder.routine
    mode = SessionMode.REPLAY if routine.source == "everos" else SessionMode.COLD_TEACH
    session = app.orchestrator.create_session(
        user_id=who.user_id,
        participant_session_id=who.participant_session_id,
        mode=mode,
        task_name=routine.name,
        task_intent=routine.name,
        skill_id=routine.id if routine.source == "everos" else None,
        start_url=routine.start_url,
    )
    app.repository.record_reminder_action(
        reminder_id=reminder.id,
        user_id=who.user_id,
        task_id=reminder.pattern.task_id,
        status="accepted",
        acted_at=datetime.now(UTC),
    )
    return ReminderActionResponse(
        reminder_id=reminder.id,
        status="accepted",
        session=session,
    )


async def _current_reminders(
    who: AuthenticatedParticipant,
    app: AppContainer,
) -> list[ProactiveReminder]:
    routines = await app.orchestrator.list_routines(who.user_id)
    return app.orchestrator.activity_memory.reminders(
        user_id=who.user_id,
        participant_session_id=who.participant_session_id,
        routines=routines,
    )


@router.post("/v1/tasks:resolve", response_model=TaskResolveResponse)
async def resolve_task(
    body: TaskResolveRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> TaskResolveResponse:
    return await app.orchestrator.resolve_routines(who.user_id, body.query)


@router.post("/v1/tasks/{task_id}:start", response_model=SessionView)
async def start_task(
    task_id: str,
    body: TaskStartRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SessionView:
    if body.participant_session_id != who.participant_session_id:
        raise HTTPException(status_code=403, detail="Participant session mismatch")
    routines = await app.orchestrator.list_routines(who.user_id)
    routine = next((item for item in routines if item.id == task_id), None)
    if routine is None:
        raise HTTPException(status_code=404, detail="Routine not found")
    mode = SessionMode.REPLAY if routine.source == "everos" else body.mode
    return app.orchestrator.create_session(
        user_id=who.user_id,
        participant_session_id=who.participant_session_id,
        mode=mode,
        task_name=routine.name,
        task_intent=routine.name,
        skill_id=routine.id if routine.source == "everos" else None,
        start_url=routine.start_url,
    )


@router.post("/v1/tasks/{session_id}:end", response_model=SessionView)
async def end_task(
    session_id: UUID,
    body: TaskEndRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SessionView:
    require_session(session_id, who, app)
    return await app.orchestrator.abandon(session_id, body.reason)


@router.get("/v1/skills/{skill_id}", response_model=SkillDocument)
async def get_skill(
    skill_id: str,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SkillDocument:
    try:
        return cast(SkillDocument, await app.everos.get_skill(who.user_id, skill_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Skill not found") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="EverOS skill memory is unavailable") from error


@router.patch("/v1/skills/{skill_id}", response_model=SkillDocument)
async def revise_skill(
    skill_id: str,
    body: SkillRevisionRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SkillDocument:
    require_caregiver(who)
    try:
        current = await app.everos.get_skill(who.user_id, skill_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Skill not found") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="EverOS skill memory is unavailable") from error

    if current.revision != body.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Skill revision {body.expected_revision} is stale; "
                f"the current revision is {current.revision}."
            ),
        )

    edits_by_step = {edit.step_id: edit.instruction for edit in body.instruction_edits}
    known_step_ids = {step.step_id for step in current.steps}
    unknown_step_ids = set(edits_by_step) - known_step_ids
    if unknown_step_ids:
        unknown = ", ".join(sorted(str(step_id) for step_id in unknown_step_ids))
        raise HTTPException(status_code=422, detail=f"Skill steps were not found: {unknown}")

    revised_name = body.name if body.name is not None else current.name
    revised_steps = [
        step.model_copy(update={"instruction": edits_by_step.get(step.step_id, step.instruction)})
        for step in current.steps
    ]
    changed = revised_name != current.name or any(
        revised.instruction != original.instruction
        for original, revised in zip(current.steps, revised_steps, strict=True)
    )
    if not changed:
        raise HTTPException(
            status_code=422, detail="The requested revision does not change the skill"
        )

    revised_payload = current.model_dump()
    revised_payload.update(
        {
            "revision": current.revision + 1,
            "name": revised_name,
            "steps": revised_steps,
            "provider_skill_id": None,
            "created_at": datetime.now(UTC),
        }
    )
    revised_skill = SkillDocument.model_validate(revised_payload)
    try:
        saved_value = await app.everos.save_skill_revision(
            who.user_id,
            skill_id,
            revised_skill,
            body.reason,
        )
        saved = SkillDocument.model_validate(saved_value)
    except Exception as error:
        raise skill_operation_unavailable(error, "immutable skill revision") from error

    if (
        saved.skill_key != current.skill_key
        or saved.revision != current.revision + 1
        or saved.source_session_id != current.source_session_id
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "EverOS returned an invalid skill revision; the local skill cache was not changed."
            ),
        )
    invalidate_cached_skill(app, current, skill_id)
    return saved


@router.delete("/v1/skills/{skill_id}", response_model=SkillDeleteResponse)
async def delete_skill(
    skill_id: str,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> SkillDeleteResponse:
    require_caregiver(who)
    try:
        current = await app.everos.get_skill(who.user_id, skill_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Skill not found") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="EverOS skill memory is unavailable") from error

    try:
        await app.everos.delete_skill(who.user_id, skill_id)
    except Exception as error:
        raise skill_operation_unavailable(error, "selective skill deletion") from error
    invalidate_cached_skill(app, current, skill_id)
    return SkillDeleteResponse(skill_id=skill_id)


@router.post(
    "/v1/uploads",
    response_model=ReviewedBillUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_reviewed_bill(
    document: Annotated[UploadFile, File(description="Caregiver-reviewed bill")],
    reviewed: Annotated[bool, Form()],
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> ReviewedBillUploadResponse:
    require_caregiver(who)
    if not reviewed:
        raise HTTPException(
            status_code=422, detail="The caregiver must review the bill before upload"
        )

    allowed_types = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }
    suffix = allowed_types.get(document.content_type or "")
    if suffix is None:
        raise HTTPException(
            status_code=415,
            detail="Reviewed bills must be PDF, JPEG, PNG, HEIC, or HEIF files.",
        )

    max_upload_bytes = 10 * 1024 * 1024
    temporary = tempfile.NamedTemporaryFile(
        prefix="webaccessible-bill-", suffix=suffix, delete=False
    )
    temporary_path = Path(temporary.name)
    size = 0
    try:
        with temporary:
            while chunk := await document.read(1024 * 1024):
                size += len(chunk)
                if size > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Reviewed bill uploads are limited to 10 MB.",
                    )
                temporary.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="The reviewed bill file is empty")

        try:
            uploaded = await app.everos.upload_reviewed(temporary_path, who.user_id)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="EverOS could not complete the reviewed bill upload.",
            ) from error
        object_key = uploaded.get("object_key") if isinstance(uploaded, dict) else None
        indexing_status = uploaded.get("indexing_status") if isinstance(uploaded, dict) else None
        if (
            not isinstance(object_key, str)
            or not object_key
            or indexing_status != "awaiting_memory_add"
        ):
            raise HTTPException(
                status_code=503,
                detail="EverOS did not return a valid reviewed upload receipt.",
            )
        return ReviewedBillUploadResponse(object_key=object_key)
    finally:
        temporary_path.unlink(missing_ok=True)
        await document.close()


@router.get("/v1/episodes:answer", response_model=EpisodeAnswer)
async def answer_episode(
    query: str,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> EpisodeAnswer:
    return await app.orchestrator.answer_episode(who.user_id, query)


@router.post("/v1/escalations/{escalation_id}/notes", response_model=EscalationView)
async def add_escalation_note(
    escalation_id: UUID,
    body: EscalationNoteRequest,
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> EscalationView:
    if who.role != ParticipantRole.CAREGIVER.value:
        raise HTTPException(status_code=403, detail="Caregiver capability required")
    try:
        escalation = app.repository.update_escalation_note(
            escalation_id, body.author_name, body.text
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Escalation not found") from error
    if escalation.user_id != who.user_id:
        raise HTTPException(status_code=403, detail="Escalation not available")
    app.repository.enqueue(
        "escalation",
        f"{escalation.id}:caregiver-response:{escalation.updated_at.isoformat()}",
        {
            "escalation_id": str(escalation.id),
            "session_id": str(escalation.session_id),
            "run_id": str(escalation.session_id),
            "user_id": escalation.user_id,
            "reason": escalation.reason,
            "status": escalation.status.value,
            "caregiver_response_status": escalation.status.value,
            "caregiver_response_metadata": {"author_name": body.author_name},
            "caregiver_response_at": escalation.updated_at.isoformat(),
            "source_environment": app.settings.app_env.value,
            "updated_at": escalation.updated_at.isoformat(),
        },
    )
    await app.event_hub.publish(
        escalation.session_id,
        {"type": "caregiver_note", "author_name": body.author_name, "text": body.text},
    )
    return escalation


@router.get("/v1/caregivers/me/dashboard", response_model=CaregiverDashboard)
async def caregiver_dashboard(
    who: Annotated[AuthenticatedParticipant, Depends(participant)],
    app: Annotated[AppContainer, Depends(container)],
) -> CaregiverDashboard:
    if who.role != ParticipantRole.CAREGIVER.value:
        raise HTTPException(status_code=403, detail="Caregiver capability required")
    snowflake_status = await app.snowflake.readiness()
    try:
        costs = await app.snowflake.cost_runs(who.user_id)
    except Exception:
        costs = []
    try:
        if not app.settings.everos_configured:
            raise RuntimeError("unconfigured")
        await app.everos.list_routines(who.user_id)
        memory_status = ProviderReadiness(
            state=ProviderState.AUTHORIZED,
            configured=True,
            reachable=True,
            authorized=True,
            last_checked_at=datetime.now(UTC),
            detail="EverOS routine and completion memory is authorized.",
        )
    except Exception as error:
        memory_status = ProviderReadiness(
            state=(
                ProviderState.UNCONFIGURED
                if not app.settings.everos_configured
                else ProviderState.UNAVAILABLE
            ),
            configured=app.settings.everos_configured,
            reachable=False,
            authorized=False,
            last_checked_at=datetime.now(UTC),
            error_code=type(error).__name__,
            detail="EverOS routine and completion memory is unavailable.",
        )
    return CaregiverDashboard(
        user_id=who.user_id,
        sessions=app.repository.list_sessions(who.user_id),
        escalations=app.repository.list_escalations(who.user_id),
        cost_runs=costs,
        memory_status=memory_status,
        telemetry_status=snowflake_status,
    )
