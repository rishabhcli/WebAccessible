from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuntimeMode(StrEnum):
    TEST = "test"
    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"


class ProviderState(StrEnum):
    UNCONFIGURED = "unconfigured"
    CONFIGURED = "configured"
    REACHABLE = "reachable"
    AUTHORIZED = "authorized"
    UNAVAILABLE = "unavailable"
    CAPACITY_EXHAUSTED = "capacity_exhausted"


class ProviderReadiness(StrictModel):
    state: ProviderState
    configured: bool
    reachable: bool = False
    authorized: bool = False
    last_checked_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=80)
    detail: str | None = Field(default=None, max_length=220)


class ReadinessResponse(StrictModel):
    mode: RuntimeMode
    ready: bool
    fixture_mode: bool = False
    capabilities: dict[str, ProviderReadiness]
    checked_at: datetime = Field(default_factory=utc_now)


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["webaccessible-api"] = "webaccessible-api"
    version: str


class ParticipantRole(StrEnum):
    USER = "user"
    CAREGIVER = "caregiver"


class ParticipantSessionRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9:_-]+$")
    participant_name: str = Field(min_length=1, max_length=80)
    role: ParticipantRole = ParticipantRole.USER
    reading_size: Literal["standard", "large", "largest"] = "large"
    voice_enabled: bool = False
    caregiver_mobile: str | None = Field(default=None, min_length=7, max_length=32)
    timezone: str = Field(default="America/Los_Angeles", max_length=80)


class ParticipantSessionResponse(StrictModel):
    participant_session_id: UUID
    access_token: str
    expires_at: datetime
    user_id: str
    role: ParticipantRole


class SessionMode(StrEnum):
    OBSERVE = "observe"
    CAREGIVER_RECORD = "caregiver_record"
    COLD_TEACH = "cold_teach"
    REPLAY = "replay"


class SessionState(StrEnum):
    CREATED = "created"
    OBSERVING = "observing"
    HELP_OFFERED = "help_offered"
    GUIDING = "guiding"
    AWAITING_USER_ACTION = "awaiting_user_action"
    VERIFYING = "verifying"
    REROUTING = "rerouting"
    REPAIRING = "repairing"
    SAFETY_PAUSED = "safety_paused"
    COMPLETED = "completed"
    PREPARED = "prepared"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"
    FAILED = "failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


TERMINAL_STATES = {
    SessionState.COMPLETED,
    SessionState.PREPARED,
    SessionState.ESCALATED,
    SessionState.ABANDONED,
    SessionState.FAILED,
}


class GuidanceMode(StrEnum):
    NONE = "none"
    COLD = "cold"
    REPLAY = "replay"
    REPAIR = "repair"


class SyncState(StrEnum):
    PENDING = "sync_pending"
    SYNCED = "synced"
    FAILED = "sync_failed"


class SessionCreateRequest(StrictModel):
    mode: SessionMode
    task_name: str = Field(min_length=1, max_length=160)
    task_intent: str = Field(min_length=1, max_length=320)
    skill_id: str | None = Field(default=None, max_length=160)
    start_url: HttpUrl | None = None


class SessionView(StrictModel):
    id: UUID
    user_id: str
    participant_session_id: UUID
    mode: SessionMode
    state: SessionState
    state_version: int = Field(ge=0)
    task_name: str
    task_intent: str
    start_url: str
    skill_id: str | None = None
    skill_revision: int | None = None
    browserbase_session_id: str | None = None
    browser_status: str = "not_started"
    current_instruction: str | None = None
    guidance_mode: GuidanceMode = GuidanceMode.NONE
    current_step_index: int = Field(default=0, ge=0)
    total_steps: int | None = Field(default=None, ge=0)
    safety_message: str | None = None
    terminal_message: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    sync_state: SyncState = SyncState.PENDING
    repair_attempts: int = Field(default=0, ge=0, le=2)
    created_at: datetime
    updated_at: datetime


class BrowserSessionView(StrictModel):
    web_session_id: UUID
    browserbase_session_id: str
    live_view_url: str | None = None
    status: str
    start_url: str
    created_at: datetime


class EventType(StrEnum):
    SESSION_STARTED = "session_started"
    PAGE_OBSERVED = "page_observed"
    NAVIGATION_OBSERVED = "navigation_observed"
    INTERACTION_OBSERVED = "interaction_observed"
    FORM_PROGRESS_OBSERVED = "form_progress_observed"
    HELP_REQUESTED = "help_requested"
    GUIDANCE_PRESENTED = "guidance_presented"
    GUIDANCE_DISMISSED = "guidance_dismissed"
    TARGET_RESOLVED = "target_resolved"
    USER_ACTION_OBSERVED = "user_action_observed"
    VERIFICATION_OBSERVED = "verification_observed"
    TASK_ABANDONED = "task_abandoned"
    SESSION_ENDED = "session_ended"


class SensitivityFlag(StrEnum):
    PASSWORD = "password"
    PAYMENT = "payment"
    IDENTITY = "identity"
    BANK = "bank"
    HIDDEN = "hidden"
    TOKEN = "token"


class BoundingRect(StrictModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class ElementCandidate(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=96)
    role: str | None = Field(default=None, max_length=40)
    accessible_name: str | None = Field(default=None, max_length=180)
    visible_text: str | None = Field(default=None, max_length=180)
    tag_name: Literal[
        "a", "button", "input", "select", "textarea", "summary", "option", "label", "div", "span"
    ]
    input_type: str | None = Field(default=None, max_length=32)
    visible: bool
    enabled: bool
    focusable: bool
    checked: bool | None = None
    bounding_rect: BoundingRect
    href_origin: str | None = Field(default=None, max_length=240)
    href_redacted_path: str | None = Field(default=None, max_length=240)
    sensitivity_flags: list[SensitivityFlag] = Field(default_factory=list, max_length=8)


class EventEnvelope(StrictModel):
    contract_version: Literal["1.0"] = "1.0"
    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    user_id: str = Field(min_length=1, max_length=96)
    browserbase_session_id: str = Field(min_length=1, max_length=160)
    page_id: str = Field(min_length=1, max_length=120)
    page_instance_id: UUID
    sequence_no: int = Field(ge=0)
    occurred_at: datetime = Field(default_factory=utc_now)
    origin: str = Field(min_length=1, max_length=240)
    redacted_path: str = Field(default="/", max_length=240)
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("origin")
    @classmethod
    def origin_must_not_contain_path(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("origin must be an http(s) origin")
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


class EventBatchRequest(StrictModel):
    events: Annotated[list[EventEnvelope], Field(min_length=1, max_length=100)]
    expected_state_version: int | None = Field(default=None, ge=0)


class EventBatchAck(StrictModel):
    accepted_event_ids: list[UUID]
    duplicate_event_ids: list[UUID] = Field(default_factory=list)
    highest_sequence_no: int
    server_state_version: int
    session: SessionView
    command: BackendCommand | None = None


class SelectorType(StrEnum):
    ARIA = "aria"
    TEXT = "text"
    CSS = "css"


class SelectorSpec(StrictModel):
    type: SelectorType
    role: str | None = Field(default=None, max_length=40)
    value: str = Field(min_length=1, max_length=320)


class SelectorBundle(StrictModel):
    selectors: Annotated[list[SelectorSpec], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def ordered_selectors(self) -> SelectorBundle:
        rank = {SelectorType.ARIA: 0, SelectorType.TEXT: 1, SelectorType.CSS: 2}
        values = [rank[item.type] for item in self.selectors]
        if values != sorted(values) or len(values) != len(set(values)):
            raise ValueError("selectors must be unique and ordered aria, text, css")
        return self


class VerificationType(StrEnum):
    URL_PATH_EQUALS = "url_path_equals"
    URL_PATH_MATCHES = "url_path_matches"
    ELEMENT_PRESENT = "element_present"
    ELEMENT_ABSENT = "element_absent"
    ARIA_STATE_EQUALS = "aria_state_equals"
    VISIBLE_TEXT_PRESENT = "visible_text_present"
    PAGE_TITLE_CONTAINS = "page_title_contains"
    SAFE_TERMINAL_REACHED = "safe_terminal_reached"


class VerificationPredicate(StrictModel):
    type: VerificationType
    value: str = Field(min_length=1, max_length=320)
    selector: SelectorBundle | None = None
    state_name: str | None = Field(default=None, max_length=48)


class SafetyClassification(StrEnum):
    SAFE = "safe"
    MONEY = "money"
    IDENTITY = "identity"
    DELETION = "deletion"
    SUSPICIOUS = "suspicious"
    UNKNOWN = "unknown"


class Amount(StrictModel):
    value: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    source: Literal["page_verified", "reviewed_fact", "unknown"]


class GuidanceDecision(StrictModel):
    instruction: str = Field(min_length=1, max_length=240)
    target_candidate_id: str = Field(min_length=1, max_length=96)
    expected_transition: VerificationPredicate
    confidence: float = Field(ge=0, le=1)
    safety_classification: SafetyClassification
    amount: Amount | None = None
    rationale_code: Literal[
        "task_match",
        "next_control",
        "route_recovery",
        "selector_repair",
        "safe_stop",
        "insufficient_context",
    ]

    @field_validator("instruction")
    @classmethod
    def one_sentence(cls, value: str) -> str:
        if "\n" in value or value.count(".") + value.count("!") + value.count("?") > 1:
            raise ValueError("instruction must be one sentence")
        return value


class CommandType(StrEnum):
    NONE = "none"
    OFFER_HELP = "offer_help"
    PRESENT_GUIDANCE = "present_guidance"
    VERIFYING = "verifying"
    SAFETY_PAUSE = "safety_pause"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    PREPARED = "prepared"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class SafetyPresentation(StrictModel):
    classification: SafetyClassification
    message: str = Field(min_length=1, max_length=320)
    irreversible_action: str | None = Field(default=None, max_length=160)
    amount: Amount | None = None


class TargetCommand(StrictModel):
    candidate_id: str
    selectors: SelectorBundle


class BackendCommand(StrictModel):
    command_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    server_state_version: int = Field(ge=0)
    command_type: CommandType
    page_instance_id: UUID | None = None
    instruction: str | None = Field(default=None, max_length=240)
    target: TargetCommand | None = None
    expected_transition: VerificationPredicate | None = None
    safety: SafetyPresentation | None = None


class SkillOutcome(StrEnum):
    COMPLETED = "completed"
    PREPARED = "prepared"


class RepairRecord(StrictModel):
    repaired_at: datetime
    source_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=160)


class SkillStep(StrictModel):
    step_id: UUID = Field(default_factory=uuid4)
    instruction: str = Field(min_length=1, max_length=240)
    selectors: SelectorBundle
    preconditions: list[VerificationPredicate] = Field(default_factory=list, max_length=5)
    expected_transition: VerificationPredicate
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    irreversible: bool = False
    irreversible_description: str | None = Field(default=None, max_length=160)
    amount_source: str | None = Field(default=None, max_length=96)
    repair_history: list[RepairRecord] = Field(default_factory=list)


class SkillDocument(StrictModel):
    schema_version: Literal[1] = 1
    skill_key: UUID = Field(default_factory=uuid4)
    revision: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=160)
    start_url: HttpUrl
    allowed_origins: Annotated[list[str], Field(min_length=1, max_length=8)]
    source_session_id: UUID
    task_outcome: SkillOutcome
    steps: Annotated[list[SkillStep], Field(min_length=1, max_length=40)]
    provider_skill_id: str | None = None
    provider_case_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class SkillInstructionEdit(StrictModel):
    step_id: UUID
    instruction: str = Field(min_length=1, max_length=240)


class SkillRevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    instruction_edits: list[SkillInstructionEdit] = Field(default_factory=list, max_length=40)
    reason: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_revision_edits(self) -> SkillRevisionRequest:
        if self.name is None and not self.instruction_edits:
            raise ValueError("a skill revision must change the name or at least one instruction")
        step_ids = [edit.step_id for edit in self.instruction_edits]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("instruction edits must identify each step only once")
        return self


class SkillDeleteResponse(StrictModel):
    skill_id: str
    deleted: Literal[True] = True


class ReviewedBillUploadResponse(StrictModel):
    object_key: str
    indexing_status: Literal["awaiting_memory_add"] = "awaiting_memory_add"
    reviewed: Literal[True] = True


class RoutineSummary(StrictModel):
    id: str
    skill_key: UUID | None = None
    revision: int = Field(default=1, ge=1)
    name: str
    description: str | None = None
    start_url: str
    last_completed_at: datetime | None = None
    source: Literal["everos", "starter"] = "everos"


class TaskResolveRequest(StrictModel):
    query: str = Field(min_length=1, max_length=240)


class TaskResolveResponse(StrictModel):
    query: str
    routines: list[RoutineSummary]
    requires_confirmation: Literal[True] = True


class TaskStartRequest(StrictModel):
    mode: SessionMode
    participant_session_id: UUID


class TaskEndRequest(StrictModel):
    reason: Literal["cancelled", "abandoned", "participant_stop"]


class EpisodeAnswer(StrictModel):
    found: bool
    answer: str
    occurred_at: datetime | None = None
    amount: Decimal | None = None
    currency: str | None = None
    provider_episode_id: str | None = None


class EscalationStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class EscalationNoteRequest(StrictModel):
    author_name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=280)


class EscalationView(StrictModel):
    id: UUID
    session_id: UUID
    user_id: str
    reason: str
    status: EscalationStatus
    caregiver_note: str | None = None
    caregiver_name: str | None = None
    created_at: datetime
    updated_at: datetime


class CaregiverDashboard(StrictModel):
    user_id: str
    sessions: list[SessionView]
    escalations: list[EscalationView]
    cost_runs: list[dict[str, Any]]
    memory_status: ProviderReadiness
    telemetry_status: ProviderReadiness
