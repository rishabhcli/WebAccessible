from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from backend.app.browser.controller import BrowserController
from backend.app.contracts.models import (
    BackendCommand,
    CommandType,
    ElementCandidate,
    GuidanceDecision,
    GuidanceMode,
    SafetyPresentation,
    SelectorBundle,
    SelectorSpec,
    SelectorType,
    SessionView,
    TargetCommand,
)
from backend.app.domain.safety import SafetyPolicy
from backend.app.persistence.repository import OperationalRepository
from backend.app.services.cost_calculator import ActualTokenUsage, CostCalculator
from backend.app.services.scam_shield import ScamShieldService


@dataclass(frozen=True)
class GuidanceResult:
    command: BackendCommand
    decision: GuidanceDecision | None
    candidate: ElementCandidate | None
    blocked: bool
    should_escalate: bool = False
    unavailable_code: str | None = None


class GuidanceService:
    def __init__(
        self,
        *,
        model_adapter: Any,
        browser: BrowserController,
        repository: OperationalRepository,
        safety_policy: SafetyPolicy,
        model_name: str,
        rate_card_version: str,
        cost_calculator: CostCalculator,
        source_environment: str,
        scam_shield: ScamShieldService | None = None,
    ) -> None:
        self.model_adapter = model_adapter
        self.browser = browser
        self.repository = repository
        self.safety_policy = safety_policy
        self.model_name = model_name
        self.rate_card_version = rate_card_version
        self.cost_calculator = cost_calculator
        self.source_environment = source_environment
        self.scam_shield = scam_shield

    async def decide(
        self,
        *,
        session: SessionView,
        candidates: list[ElementCandidate],
        allowed_origins: list[str],
        current_origin: str,
        mode: GuidanceMode,
        profile: dict[str, Any] | None = None,
    ) -> GuidanceResult:
        call_id = uuid4()
        start = monotonic()
        requested_at = datetime.now(UTC)
        usage: dict[str, Any] = {}
        try:
            raw = await self.model_adapter.decide(
                task_intent=session.task_intent,
                candidates=candidates,
                profile=profile,
                mode=mode.value,
            )
            if isinstance(raw, tuple):
                decision_value, usage = raw
            else:
                decision_value = getattr(raw, "decision", raw)
                usage = getattr(raw, "usage", {}) or {}
            decision = (
                decision_value
                if isinstance(decision_value, GuidanceDecision)
                else GuidanceDecision.model_validate(decision_value)
            )
            candidate = next(
                (item for item in candidates if item.candidate_id == decision.target_candidate_id),
                None,
            )
            if candidate is None or not candidate.visible or not candidate.enabled:
                raise ValueError("model selected an unavailable candidate")
            safety = self.safety_policy.evaluate(
                decision=decision,
                target=candidate,
                current_origin=current_origin,
                allowed_origins=allowed_origins,
            )
            latency_ms = round((monotonic() - start) * 1000)
            await self._record_call(
                call_id=call_id,
                session=session,
                mode=mode,
                usage=usage,
                latency_ms=latency_ms,
                status="completed",
                requested_at=requested_at,
            )
            if decision.confidence < 0.62:
                return self._pause(
                    session,
                    SafetyPresentation(
                        classification=decision.safety_classification,
                        message="I am not certain enough about this page, so I have paused here.",
                    ),
                    decision,
                    candidate,
                    escalate=True,
                )
            if not safety.allowed:
                assert safety.presentation is not None
                presentation = await self._sharpen_pause(
                    safety.presentation,
                    candidates=candidates,
                    escalate=safety.should_escalate,
                )
                return self._pause(
                    session,
                    presentation,
                    decision,
                    candidate,
                    escalate=safety.should_escalate,
                )
            highlighted = await self.browser.highlight(session.id, candidate.candidate_id)
            if not highlighted:
                raise ValueError("candidate became stale before highlighting")
            return GuidanceResult(
                command=BackendCommand(
                    session_id=session.id,
                    server_state_version=session.state_version + 1,
                    command_type=CommandType.PRESENT_GUIDANCE,
                    instruction=decision.instruction,
                    target=TargetCommand(
                        candidate_id=candidate.candidate_id,
                        selectors=self._selectors(candidate),
                    ),
                    expected_transition=decision.expected_transition,
                ),
                decision=decision,
                candidate=candidate,
                blocked=False,
            )
        except Exception as error:
            latency_ms = round((monotonic() - start) * 1000)
            await self._record_call(
                call_id=call_id,
                session=session,
                mode=mode,
                usage=usage,
                latency_ms=latency_ms,
                status="failed",
                requested_at=requested_at,
            )
            return GuidanceResult(
                command=BackendCommand(
                    session_id=session.id,
                    server_state_version=session.state_version + 1,
                    command_type=CommandType.PROVIDER_UNAVAILABLE,
                    instruction=(
                        "Guidance is unavailable right now; your browser session is still open."
                    ),
                ),
                decision=None,
                candidate=None,
                blocked=True,
                unavailable_code=type(error).__name__,
            )

    async def _sharpen_pause(
        self,
        presentation: SafetyPresentation,
        *,
        candidates: list[ElementCandidate],
        escalate: bool,
    ) -> SafetyPresentation:
        """Name the specific risky request behind an escalating pause.

        Only escalating pauses reach the classifier, which is exactly the unfamiliar-page
        and suspicious-classification path. Ordinary money confirmations on a known site
        keep their existing wording and add no latency.
        """

        if not escalate or self.scam_shield is None:
            return presentation
        page_text = " ".join(
            part
            for candidate in candidates[:24]
            for part in (candidate.accessible_name, candidate.visible_text)
            if part
        )
        verdict = await self.scam_shield.triage(page_text)
        if verdict is None:
            return presentation
        return presentation.model_copy(
            update={
                "message": f"Let's pause a moment. {verdict.message} I've let your helper know.",
                "scam_category": verdict.category,
            }
        )

    def _pause(
        self,
        session: SessionView,
        presentation: SafetyPresentation,
        decision: GuidanceDecision,
        candidate: ElementCandidate,
        *,
        escalate: bool,
    ) -> GuidanceResult:
        return GuidanceResult(
            command=BackendCommand(
                session_id=session.id,
                server_state_version=session.state_version + 1,
                command_type=CommandType.SAFETY_PAUSE,
                instruction=presentation.message,
                safety=presentation,
            ),
            decision=decision,
            candidate=candidate,
            blocked=True,
            should_escalate=escalate,
        )

    async def _record_call(
        self,
        *,
        call_id: UUID,
        session: SessionView,
        mode: GuidanceMode,
        usage: dict[str, Any],
        latency_ms: int,
        status: str,
        requested_at: datetime,
    ) -> None:
        completed_at = datetime.now(UTC)
        input_tokens = self._token_count(usage.get("input_tokens"))
        output_tokens = self._token_count(usage.get("output_tokens"))
        usage_status = (
            "actual" if input_tokens is not None and output_tokens is not None else "unavailable"
        )
        model = str(usage.get("model") or self.model_name)
        provider = str(usage.get("provider") or "snowflake_cortex")
        rate_card_version = str(usage.get("rate_card_version") or self.rate_card_version)
        query_id = usage.get("query_id")
        provider_response_id_hash = (
            hashlib.sha256(str(query_id).encode("utf-8")).hexdigest() if query_id else None
        )
        local_values = {
            "call_id": str(call_id),
            "session_id": str(session.id),
            "step_id": None,
            "guidance_mode": mode.value,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "status": status,
            "rate_card_version": rate_card_version,
            "cost_usd": None,
        }
        model_call = {
            "call_id": str(call_id),
            "session_id": str(session.id),
            "run_id": str(session.id),
            "user_id": session.user_id,
            "event_id": None,
            "step_id": None,
            "guidance_mode": mode.value,
            "provider": provider,
            "model": model,
            "model_version": usage.get("model_version"),
            "estimated_input_tokens": self._token_count(usage.get("estimated_input_tokens")),
            "actual_input_tokens": input_tokens,
            "actual_cached_input_tokens": 0 if usage_status == "actual" else None,
            "actual_reasoning_tokens": 0 if usage_status == "actual" else None,
            "actual_output_tokens": output_tokens,
            "usage_status": usage_status,
            "latency_ms": latency_ms,
            "status": status,
            "provider_response_id_hash": provider_response_id_hash,
            "source_environment": self.source_environment,
            "requested_at": requested_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "synchronized_at": completed_at.isoformat(),
        }

        calculated = None
        if usage_status == "actual" and input_tokens is not None and output_tokens is not None:
            try:
                calculated = await self.cost_calculator.calculate(
                    call_id=str(call_id),
                    session_id=str(session.id),
                    run_id=str(session.id),
                    user_id=session.user_id,
                    provider=provider,
                    model=model,
                    model_version=usage.get("model_version"),
                    rate_card_version=rate_card_version,
                    usage=ActualTokenUsage(
                        input_tokens=input_tokens,
                        cached_input_tokens=0,
                        reasoning_tokens=0,
                        output_tokens=output_tokens,
                    ),
                    usage_status=usage_status,
                    effective_at=completed_at,
                    source_environment=self.source_environment,
                )
            except Exception:
                calculated = None
            if calculated is not None:
                local_values["cost_usd"] = str(calculated.amount_usd)

        self.repository.save_model_call(local_values)
        self.repository.enqueue("model_call", str(call_id), model_call)
        if calculated is not None:
            self.repository.enqueue(
                "model_cost",
                calculated.cost_id,
                calculated.to_outbox_payload(),
            )

    @staticmethod
    def _token_count(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result >= 0 else None

    @staticmethod
    def _selectors(candidate: ElementCandidate) -> SelectorBundle:
        selectors: list[SelectorSpec] = []
        if candidate.accessible_name:
            selectors.append(
                SelectorSpec(
                    type=SelectorType.ARIA,
                    role=candidate.role or "button",
                    value=candidate.accessible_name,
                )
            )
        if candidate.visible_text:
            selectors.append(SelectorSpec(type=SelectorType.TEXT, value=candidate.visible_text))
        return SelectorBundle(
            selectors=selectors[:2]
            or [SelectorSpec(type=SelectorType.TEXT, value=candidate.candidate_id)]
        )
