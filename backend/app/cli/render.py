"""Human-readable rendering of caregiver memory administration receipts.

Text output is derived from the same receipt object that ``--format json``
prints, so the terminal and a later caregiver UI can never disagree. Skill
output is Markdown whose YAML front matter starts at byte 0, which keeps
``skill show > routine.md`` parseable by the canonical skill parser.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from backend.app.cli.receipts import TOOL_NAME, Receipt, ReceiptStatus

_INDENT: Final = "  "
_MISSING: Final = "-"

# Structures rendered by a dedicated renderer instead of the generic key list.
_STRUCTURED_DATA_KEYS: Final = frozenset(
    {
        "episodes",
        "markdown",
        "other_categories",
        "proposed_markdown",
        "proposed_skill",
        "routines",
        "saved_skill",
        "setup_fields",
        "skill",
    }
)
_MARKDOWN_DATA_KEYS: Final = ("proposed_markdown", "markdown")


def render_text(receipt: Receipt) -> str:
    """Return the terminal rendering for one receipt."""

    if receipt.status is not ReceiptStatus.OK:
        return _render_failure(receipt)
    renderer = _RENDERERS.get(receipt.command)
    if renderer is None:
        body = [f"{receipt.command}: completed.", *_render_data_lines(receipt.data)]
        return _finalize(body + _render_notes(receipt) + _render_redaction(receipt))
    body = renderer.body(receipt)
    notes = _render_notes(receipt, markdown=renderer.markdown)
    return _finalize(body + notes + _render_redaction(receipt))


def _render_routines(receipt: Receipt) -> list[str]:
    data = receipt.data
    routines = _sequence(data.get("routines"))
    lines = [
        f"EverOS routines for user {_text(receipt.user_id)}",
        f"Agent memory scope: {_text(receipt.agent_memory_scope)}",
        "",
        f"Validated routines: {len(routines)} of "
        f"{_text(data.get('provider_record_count'))} EverOS agent_skill record(s)",
        "",
    ]
    if not routines:
        lines.append("EverOS returned no validated routine for this user.")
    for index, entry in enumerate(routines, start=1):
        item = _mapping(entry)
        lines.extend(
            [
                f"{index}. {_text(item.get('name'))}",
                f"{_INDENT}provider_skill_id: {_text(item.get('id'))}",
                f"{_INDENT}skill_key:         {_text(item.get('skill_key'))}",
                f"{_INDENT}revision:          {_text(item.get('revision'))}",
                f"{_INDENT}start_url:         {_text(item.get('start_url'))}",
                f"{_INDENT}description:       {_text(item.get('description'))}",
                f"{_INDENT}last_completed_at: {_text(item.get('last_completed_at'))}",
                f"{_INDENT}source:            {_text(item.get('source'))}",
                "",
            ]
        )
    unvalidated = _sequence(data.get("unvalidated_provider_skill_ids"))
    if unvalidated:
        lines.append("EverOS records that did not validate (listed by provider ID only):")
        lines.extend(f"{_INDENT}- {_text(item)}" for item in unvalidated)
    return lines


def _render_skill_show(receipt: Receipt) -> list[str]:
    data = receipt.data
    lines = _text(data.get("markdown")).rstrip("\n").split("\n")
    lines.extend(
        [
            "",
            "## Provider references",
            "",
            f"- Requested skill ID: `{_text(data.get('requested_skill_id'))}`",
            f"- Provider skill ID: `{_text(data.get('provider_skill_id'))}`",
            f"- Provider case IDs: {_code_list(_sequence(data.get('provider_case_ids')))}",
            f"- Agent memory scope: `{_text(receipt.agent_memory_scope)}`",
            f"- Revision: {_text(data.get('revision'))}",
            f"- Validation: schema_version {_text(data.get('schema_version'))} validated against"
            " the WebAccessible skill contract.",
        ]
    )
    return lines


def _render_episodes(receipt: Receipt) -> list[str]:
    data = receipt.data
    episodes = _sequence(data.get("episodes"))
    lines = [
        f"EverOS episode search for user {_text(receipt.user_id)}",
        f"Query: {_text(data.get('query'))}",
        f"Requested top_k: {_text(data.get('top_k'))}",
        "",
        f"Episodes returned: {len(episodes)}",
        "",
    ]
    if not episodes:
        lines.append("EverOS returned no completion episode for this query.")
    for index, entry in enumerate(episodes, start=1):
        item = _mapping(entry)
        lines.extend(
            [
                f"{index}. {_text(item.get('summary'))}",
                f"{_INDENT}provider_episode_id: {_text(item.get('provider_episode_id'))}",
                f"{_INDENT}session_id:          {_text(item.get('session_id'))}",
                f"{_INDENT}timestamp:           {_text(item.get('timestamp'))}",
                f"{_INDENT}indexing_status:     {_text(item.get('indexing_status'))}",
                f"{_INDENT}amount:              {_text(item.get('amount'))}"
                f" {_text(item.get('currency'))}",
                f"{_INDENT}fields not shown:    "
                f"{_plain_list(_sequence(item.get('fields_not_shown')))}",
                "",
            ]
        )
    return lines


def _render_profile(receipt: Receipt) -> list[str]:
    data = receipt.data
    lines = [
        f"EverOS profile status for user {_text(receipt.user_id)}",
        f"Profile memory present: {_text(data.get('profile_present'))}",
        f"Profile records: {_text(data.get('profile_record_count'))}"
        f" (provider IDs: {_plain_list(_sequence(data.get('profile_record_ids')))})",
        f"Caregiver contact stored: {_text(data.get('caregiver_mobile_stored'))}",
        "",
        "Reviewed WebAccessible setup fields",
    ]
    for entry in _sequence(data.get("setup_fields")):
        item = _mapping(entry)
        state = "present" if item.get("present") else "absent"
        if item.get("value_withheld"):
            value = "value withheld"
        else:
            value = f"value: {_text(item.get('value'))}"
        lines.extend(
            [
                f"{_INDENT}{_text(item.get('field'))}",
                f"{_INDENT * 2}category:       {_text(item.get('category'))}",
                f"{_INDENT * 2}state:          {state} ({_text(item.get('item_count'))} item(s))",
                f"{_INDENT * 2}classification: {_text(item.get('classification'))}",
                f"{_INDENT * 2}{value}",
                f"{_INDENT * 2}item_ids:       {_plain_list(_sequence(item.get('item_ids')))}",
            ]
        )
    other = _sequence(data.get("other_categories"))
    if other:
        lines.extend(["", "Other profile categories (values withheld)"])
        for entry in other:
            item = _mapping(entry)
            lines.append(
                f"{_INDENT}{_text(item.get('category'))}: "
                f"{_text(item.get('item_count'))} item(s), "
                f"item_ids {_plain_list(_sequence(item.get('item_ids')))}"
            )
    return lines


def _render_upload(receipt: Receipt) -> list[str]:
    data = receipt.data
    return [
        f"EverOS accepted the reviewed upload for user {_text(receipt.user_id)}.",
        "",
        f"{_INDENT}file_name:           {_text(data.get('file_name'))}",
        f"{_INDENT}content_type:        {_text(data.get('content_type'))}",
        f"{_INDENT}size_bytes:          {_text(data.get('size_bytes'))}",
        f"{_INDENT}sha256:              {_text(data.get('sha256'))}",
        f"{_INDENT}reviewed:            {_text(data.get('reviewed'))}",
        f"{_INDENT}provider_object_key: {_text(data.get('provider_object_key'))}",
        f"{_INDENT}indexing_status:     {_text(data.get('indexing_status'))}",
        f"{_INDENT}memory_changed:      {_text(receipt.memory_changed)}",
    ]


def _render_skill_write(receipt: Receipt) -> list[str]:
    """Render the success path of a skill write the provider actually performed."""

    data = receipt.data
    lines = [
        f"{receipt.command}: EverOS reported that the operation succeeded.",
        "",
        *_render_data_lines(data),
    ]
    markdown = _first_markdown(data)
    if markdown is not None:
        lines.extend(["", "## Saved revision", "", *markdown])
    return lines


def _render_failure(receipt: Receipt) -> str:
    error = receipt.error
    lines = [
        f"{TOOL_NAME}: {receipt.command} did not complete.",
        f"status:         {receipt.status.value}",
        f"memory changed: {_text(receipt.memory_changed)}",
    ]
    if receipt.provider_limitation is not None:
        lines.append(f"provider limit: {receipt.provider_limitation}")
    if error is not None:
        if error.message != receipt.provider_limitation:
            lines.append(f"reason:         {error.message}")
        lines.append(f"error code:     {error.code} (retryable: {_text(error.retryable)})")
        if error.provider_status_code is not None:
            lines.append(f"provider status: {error.provider_status_code}")
    details = _render_data_lines(receipt.data)
    if details:
        lines.extend(["", "details:", *details])
    markdown = _first_markdown(receipt.data)
    if markdown is not None:
        lines.extend(["", "validated locally and not saved:", "", *markdown])
    return _finalize(lines + _render_notes(receipt) + _render_redaction(receipt))


def _render_notes(receipt: Receipt, *, markdown: bool = False) -> list[str]:
    if not receipt.notes:
        return []
    if markdown:
        return ["", "## Notes", "", *(f"- {note}" for note in receipt.notes)]
    return ["", "Notes", *(f"{_INDENT}- {note}" for note in receipt.notes)]


def _render_redaction(receipt: Receipt) -> list[str]:
    if receipt.redaction_count <= 0:
        return []
    plural = "" if receipt.redaction_count == 1 else "s"
    return [
        "",
        f"Redacted {receipt.redaction_count} contact- or token-shaped value{plural} "
        "from provider text before display.",
    ]


def _render_data_lines(data: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in data.items():
        if key in _STRUCTURED_DATA_KEYS:
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            lines.append(f"{_INDENT}{key}: {_text(value)}")
        elif isinstance(value, list):
            if all(item is None or isinstance(item, (str, int, float, bool)) for item in value):
                lines.append(f"{_INDENT}{key}: {_plain_list(value)}")
    return lines


def _first_markdown(data: Mapping[str, Any]) -> list[str] | None:
    for key in _MARKDOWN_DATA_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.rstrip("\n").split("\n")
    return None


def _finalize(lines: Sequence[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


def _text(value: Any) -> str:
    if value is None:
        return _MISSING
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return text if text else _MISSING


def _plain_list(values: Sequence[Any]) -> str:
    rendered = ", ".join(_text(value) for value in values)
    return rendered if rendered else "none"


def _code_list(values: Sequence[Any]) -> str:
    rendered = ", ".join(f"`{_text(value)}`" for value in values)
    return rendered if rendered else "none returned"


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


@dataclass(frozen=True, slots=True)
class _Renderer:
    body: Callable[[Receipt], list[str]]
    markdown: bool = False


_RENDERERS: Final[dict[str, _Renderer]] = {
    "routines.list": _Renderer(_render_routines),
    "skill.show": _Renderer(_render_skill_show, markdown=True),
    "skill.delete": _Renderer(_render_skill_write),
    "skill.revise": _Renderer(_render_skill_write, markdown=True),
    "episodes.search": _Renderer(_render_episodes),
    "profile.status": _Renderer(_render_profile),
    "upload.reviewed": _Renderer(_render_upload),
}
