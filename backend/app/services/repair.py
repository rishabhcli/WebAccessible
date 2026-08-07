from __future__ import annotations

from datetime import UTC, datetime

from backend.app.contracts.models import RepairRecord, SkillDocument, SkillStep


class RepairService:
    def revise_one_step(
        self, *, skill: SkillDocument, step_index: int, replacement: SkillStep, reason: str
    ) -> SkillDocument:
        if step_index >= len(skill.steps):
            raise IndexError("repair step index is past the skill")
        steps = list(skill.steps)
        replacement = replacement.model_copy(
            update={
                "repair_history": [
                    *steps[step_index].repair_history,
                    RepairRecord(
                        repaired_at=datetime.now(UTC), source_revision=skill.revision, reason=reason
                    ),
                ]
            }
        )
        steps[step_index] = replacement
        return skill.model_copy(
            update={"revision": skill.revision + 1, "steps": steps, "created_at": datetime.now(UTC)}
        )
