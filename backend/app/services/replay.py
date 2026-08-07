from __future__ import annotations

from dataclasses import dataclass

from backend.app.contracts.models import ElementCandidate, SelectorSpec, SkillDocument, SkillStep


@dataclass(frozen=True)
class ReplayResolution:
    step: SkillStep
    candidate: ElementCandidate | None
    matched_selector: SelectorSpec | None
    attempted_tiers: tuple[str, ...]

    @property
    def matched(self) -> bool:
        return self.candidate is not None and self.matched_selector is not None


class ReplayEngine:
    """Deterministic in-memory pre-resolution; the CDP bridge revalidates before highlighting."""

    def resolve(
        self,
        *,
        skill: SkillDocument,
        step_index: int,
        candidates: list[ElementCandidate],
    ) -> ReplayResolution:
        if step_index >= len(skill.steps):
            raise IndexError("replay step index is past the skill")
        step = skill.steps[step_index]
        attempted: list[str] = []
        for selector in step.selectors.selectors:
            attempted.append(selector.type.value)
            matches = [candidate for candidate in candidates if self._matches(selector, candidate)]
            eligible = [
                candidate for candidate in matches if candidate.visible and candidate.enabled
            ]
            if len(eligible) == 1:
                return ReplayResolution(step, eligible[0], selector, tuple(attempted))
        return ReplayResolution(step, None, None, tuple(attempted))

    @staticmethod
    def _matches(selector: SelectorSpec, candidate: ElementCandidate) -> bool:
        if selector.type.value == "aria":
            return (candidate.accessible_name or "").casefold() == selector.value.casefold() and (
                not selector.role or (candidate.role or "").casefold() == selector.role.casefold()
            )
        if selector.type.value == "text":
            return (candidate.visible_text or "").casefold() == selector.value.casefold()
        return False
