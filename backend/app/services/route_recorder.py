from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from backend.app.contracts.models import (
    ElementCandidate,
    SelectorBundle,
    SelectorSpec,
    SelectorType,
    SkillDocument,
    SkillOutcome,
    SkillStep,
    VerificationPredicate,
)
from backend.app.persistence.repository import OperationalRepository


class RouteRecorder:
    def __init__(self, repository: OperationalRepository) -> None:
        self.repository = repository

    def record_verified_step(
        self,
        *,
        session_id: UUID,
        candidate: ElementCandidate,
        instruction: str,
        css_path: str | None,
        verification: VerificationPredicate,
        irreversible: bool = False,
        irreversible_description: str | None = None,
    ) -> SkillStep:
        selectors: list[SelectorSpec] = []
        if candidate.accessible_name:
            selectors.append(
                SelectorSpec(
                    type=SelectorType.ARIA,
                    role=candidate.role or self._implicit_role(candidate.tag_name),
                    value=candidate.accessible_name,
                )
            )
        if candidate.visible_text:
            selectors.append(SelectorSpec(type=SelectorType.TEXT, value=candidate.visible_text))
        if css_path:
            selectors.append(SelectorSpec(type=SelectorType.CSS, value=css_path))
        if not selectors:
            raise ValueError("a verified route step requires at least one stable selector")

        step = SkillStep(
            instruction=instruction,
            selectors=SelectorBundle(selectors=selectors),
            expected_transition=verification,
            irreversible=irreversible,
            irreversible_description=irreversible_description,
        )
        self.repository.record_step(session_id, step)
        return step

    def compile_skill(
        self,
        *,
        session_id: UUID,
        name: str,
        start_url: str,
        outcome: SkillOutcome,
    ) -> SkillDocument:
        steps = self.repository.get_recorded_steps(session_id)
        if not steps:
            raise ValueError("a skill cannot be compiled without verified user actions")
        parsed = urlsplit(start_url)
        origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        return SkillDocument(
            name=name,
            start_url=start_url,
            allowed_origins=[origin],
            source_session_id=session_id,
            task_outcome=outcome,
            steps=steps,
        )

    @staticmethod
    def _implicit_role(tag_name: str) -> str:
        return {"a": "link", "button": "button", "input": "textbox"}.get(tag_name, "button")
