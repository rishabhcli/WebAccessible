from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import yaml

from backend.app.contracts.models import SkillDocument

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def render_skill_markdown(skill: SkillDocument) -> str:
    data = skill.model_dump(mode="json", exclude={"provider_skill_id", "provider_case_ids"})
    front_matter = yaml.safe_dump(data, sort_keys=False, allow_unicode=False).strip()
    lines = [
        "---",
        front_matter,
        "---",
        "",
        f"# {skill.name}",
        "",
        f"Revision {skill.revision} from session `{skill.source_session_id}`.",
        "",
    ]
    for index, step in enumerate(skill.steps, start=1):
        lines.extend(
            [
                f"## Step {index}",
                "",
                step.instruction,
                "",
                f"Verification: `{step.expected_transition.type.value}`.",
                "",
            ]
        )
        if step.irreversible:
            lines.extend(
                [
                    "This step pauses before the real site action.",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def parse_skill_markdown(markdown: str) -> SkillDocument:
    match = FRONT_MATTER.search(markdown)
    if not match:
        raise ValueError("skill content is missing YAML front matter")
    payload: Any = yaml.safe_load(match.group(1))
    if not isinstance(payload, dict):
        raise ValueError("skill front matter must be a mapping")
    return SkillDocument.model_validate(payload)


def provider_value(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def normalize_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
