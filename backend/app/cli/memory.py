"""Caregiver-facing EverOS memory administration CLI.

This tool is a read-mostly administration surface over the existing EverOS
ownership adapter in :mod:`backend.app.integrations.everos`. It performs no SDK
calls of its own, keeps the adapter's user-owned versus agent-owned scope
translation, and adds no second memory model.

Deliberate boundaries:

* Whole-scope deletion is never offered or attempted. ``delete_user_memory``,
  ``delete_agent_memory``, and ``delete_session_memory`` are never called from
  this package, and a refused selective deletion never falls back to them.
* Operations the installed EverOS SDK cannot perform, namely selective
  agent-skill deletion and immutable skill revision, report the provider
  limitation and exit non-zero instead of emulating the behaviour.
* Caregiver contact values, uploaded document content, provider credentials, and
  provider request bodies are never printed or written to a receipt.
* User IDs and skill IDs must be exact. No prefix, wildcard, or fuzzy
  resolution is performed, and no Case, Skill, or Episode ID is ever invented:
  every identifier printed is one EverOS returned.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Final
from uuid import UUID

import yaml
from pydantic import ValidationError

from backend.app.cli.receipts import (
    TOOL_NAME,
    TOOL_VERSION,
    ExitCode,
    Receipt,
    ReceiptError,
    ReceiptStatus,
    render_receipt_json,
)
from backend.app.cli.redaction import Redactor
from backend.app.cli.render import render_text
from backend.app.config import get_settings
from backend.app.contracts.models import SkillDocument, SkillStep
from backend.app.domain.skills import render_skill_markdown
from backend.app.integrations.everos import (
    EverOSAdapter,
    EverOSErrorCode,
    EverOSProvider,
    EverOSProviderError,
)

# Imported instead of restated so the status view names exactly the categories
# the adapter writes. The integration module is owned elsewhere and is not
# edited here, so the mapping cannot be re-exported publicly.
from backend.app.integrations.everos.client import _SETUP_PROFILE_CATEGORIES

_AGENT_SKILL_PAGE_SIZE: Final = 100
_PROFILE_PAGE_SIZE: Final = 20
_HASH_CHUNK_BYTES: Final = 1024 * 1024
_MAX_UPLOAD_BYTES: Final = 10 * 1024 * 1024
_MAX_TOP_K: Final = 100
_MAX_QUERY_LENGTH: Final = 240
_SKILL_NAME_LIMIT: Final = 160
_STEP_INSTRUCTION_LIMIT: Final = 240
_IRREVERSIBLE_DESCRIPTION_LIMIT: Final = 160
_REVISION_REASON_LIMIT: Final = 160
_SKILL_ID_MAX_LENGTH: Final = 128
_USER_ID_PATTERN: Final = re.compile(r"\A[A-Za-z0-9:_-]{1,96}\Z")
_WILDCARD_CHARACTERS: Final = frozenset("*?%")

# Mirrors the reviewed-upload allowlist enforced by ``POST /v1/uploads``. The CLI
# has no MIME header, so the caregiver-visible extension is the declared type.
_UPLOAD_CONTENT_TYPES: Final = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
}

_EPISODE_SCALAR_FIELDS: Final = (
    "id",
    "session_id",
    "type",
    "timestamp",
    "occurred_at",
    "indexing_status",
    "status",
    "amount",
    "currency",
)
_EPISODE_PROSE_FIELDS: Final = ("episode", "summary", "title", "description")
_PRIVATE_PROFILE_FIELDS: Final = frozenset({"caregiver_mobile"})
_PRIVATE_CLASSIFICATIONS: Final = frozenset({"private_contact"})
_PRIVATE_ALLOWED_USES: Final = frozenset({"caregiver_delivery_only"})

_INDEX_LAG_NOTE: Final = (
    "EverOS reads can lag 10-15 seconds behind a write, so memory saved moments ago may "
    "not appear yet. Nothing is substituted for a record EverOS did not return."
)
_NO_WHOLE_SCOPE_DELETE_NOTE: Final = (
    "This tool never deletes all user memory or all agent memory; whole-scope EverOS "
    "deletion is not exposed here and is never used as a fallback."
)
_PROFILE_PRIVACY_NOTE: Final = (
    "Values are shown only for reviewed non-private categories. Caregiver contact values "
    "stay inside EverOS and are never printed by this tool."
)
_UNAVAILABLE_NOTE: Final = (
    "EverOS memory is unavailable for this run, so no routine, skill, episode, or profile "
    "claim can be made from it."
)

_EPILOG: Final = """\
safety boundaries:
  * Whole-scope deletion is never offered or attempted; a refused selective
    deletion never falls back to deleting all user or agent memory.
  * Operations the installed EverOS SDK cannot perform report the provider
    limitation and exit 3 instead of emulating the behaviour.
  * Caregiver contact values, uploaded document content, provider credentials,
    and provider request bodies are never printed or written to a receipt.
  * User and skill IDs must be exact; no prefix, wildcard, or fuzzy matching is
    performed and no provider ID is ever invented.

exit codes:
  0  the command completed
  1  the command stopped on an unexpected internal error
  2  refused by local validation, including a missing --reviewed flag
  3  EverOS provider limitation; no memory was changed
  4  the exact ID was not found in EverOS memory
  5  EverOS memory is unavailable
  6  EverOS returned content that failed WebAccessible validation
  7  EverOS is not configured in this environment
"""


class _CommandError(Exception):
    """A CLI failure that maps onto a receipt status and an exit code."""

    status: ClassVar[ReceiptStatus] = ReceiptStatus.REFUSED
    exit_code: ClassVar[ExitCode] = ExitCode.REFUSED
    default_code: ClassVar[str] = "refused"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.retryable = retryable
        self.details = dict(details) if details is not None else {}


class _Refusal(_CommandError):
    """The caller asked for something this tool will not do."""


class _NotFound(_CommandError):
    status: ClassVar[ReceiptStatus] = ReceiptStatus.NOT_FOUND
    exit_code: ClassVar[ExitCode] = ExitCode.NOT_FOUND
    default_code: ClassVar[str] = "not_found"


class _InvalidProviderData(_CommandError):
    status: ClassVar[ReceiptStatus] = ReceiptStatus.INVALID_PROVIDER_DATA
    exit_code: ClassVar[ExitCode] = ExitCode.INVALID_PROVIDER_DATA
    default_code: ClassVar[str] = "invalid_provider_data"


class _UnexpectedFailure(_CommandError):
    """The tool itself stopped; no provider claim is made either way."""

    status: ClassVar[ReceiptStatus] = ReceiptStatus.FAILED
    exit_code: ClassVar[ExitCode] = ExitCode.UNEXPECTED
    default_code: ClassVar[str] = "unexpected_error"


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """The live adapters this CLI is allowed to use."""

    adapter: EverOSAdapter
    provider: EverOSProvider


_Handler = Callable[[MemoryContext, argparse.Namespace], Coroutine[Any, Any, Receipt]]


async def handle_routines_list(ctx: MemoryContext, args: argparse.Namespace) -> Receipt:
    """List the caregiver-visible routines EverOS holds for one exact user."""

    user_id = str(args.user_id)
    receipt = _new_receipt("routines.list", user_id)
    redactor = Redactor()
    stored = await ctx.provider.get_agent_memory(
        user_id,
        "agent_skill",
        page=1,
        page_size=_AGENT_SKILL_PAGE_SIZE,
    )
    provider_ids = _provider_record_ids(stored.data, "agent_skills")
    routines = await ctx.adapter.list_routines(user_id)
    entries: list[dict[str, Any]] = []
    for routine in routines:
        entry = routine.model_dump(mode="json")
        entry["name"] = redactor.text(str(entry.get("name") or ""))
        entry["description"] = redactor.optional(_optional_str(entry.get("description")))
        entries.append(entry)
    validated_ids = {routine.id for routine in routines}
    unvalidated = [item for item in provider_ids if item not in validated_ids]

    receipt.data = {
        "agent_memory_type": "agent_skill",
        "provider_record_count": len(provider_ids),
        "validated_routine_count": len(entries),
        "routines": entries,
        "unvalidated_provider_skill_ids": unvalidated,
    }
    receipt.redaction_count = redactor.count
    if not entries:
        receipt.add_note("EverOS returned no validated routine for this user.")
    if unvalidated:
        receipt.add_note(
            f"{len(unvalidated)} EverOS agent_skill record(s) did not validate against the "
            "WebAccessible skill contract and are listed by provider ID only. Nothing was "
            "changed and no replacement routine was invented."
        )
    receipt.add_note(_INDEX_LAG_NOTE)
    return receipt


async def handle_skill_show(ctx: MemoryContext, args: argparse.Namespace) -> Receipt:
    """Show one validated skill as readable Markdown and structured JSON."""

    user_id = str(args.user_id)
    skill_id = str(args.skill_id)
    receipt = _new_receipt("skill.show", user_id)
    redactor = Redactor()
    skill = await _load_skill(ctx, user_id, skill_id)
    displayed = _redacted_skill(skill, redactor)

    receipt.data = {
        "requested_skill_id": skill_id,
        "provider_skill_id": skill.provider_skill_id,
        "provider_case_ids": list(skill.provider_case_ids),
        "schema_version": skill.schema_version,
        "revision": skill.revision,
        "source_session_id": str(skill.source_session_id),
        "skill_validated": True,
        "skill": displayed.model_dump(mode="json"),
        "markdown": render_skill_markdown(displayed),
    }
    receipt.redaction_count = redactor.count
    receipt.add_note(
        "The front matter above is the canonical machine-readable route; the body is the "
        "caregiver-readable rendering of the same revision."
    )
    receipt.add_note(
        "Provider skill and case IDs are printed exactly as EverOS returned them."
    )
    return receipt


async def handle_episodes_search(ctx: MemoryContext, args: argparse.Namespace) -> Receipt:
    """Search user-owned completion episodes for one exact user."""

    user_id = str(args.user_id)
    query = _validated_query(args.query)
    top_k = _validated_top_k(args.top_k)
    receipt = _new_receipt("episodes.search", user_id)
    redactor = Redactor()
    result = await ctx.provider.search(user_id, query, top_k=top_k, include_profile=False)
    raw = result.user_memory.get("episodes")
    episodes_present = isinstance(raw, list)
    returned: list[Any] = list(raw) if isinstance(raw, list) else []
    records = [
        _episode_record(item, redactor) for item in returned if isinstance(item, Mapping)
    ]

    receipt.data = {
        "user_memory_type": "episode",
        "query": redactor.text(query),
        "top_k": top_k,
        "episodes_key_present": episodes_present,
        "episode_count": len(records),
        "episodes": records,
    }
    receipt.redaction_count = redactor.count
    if not records:
        receipt.add_note(
            "EverOS returned no completion episode for this query. No completion answer is "
            "inferred when memory has none."
        )
    receipt.add_note(
        "Provider episode IDs, timestamps, and indexing status are printed exactly as EverOS "
        "returned them; unlisted fields are named but not shown."
    )
    receipt.add_note(_INDEX_LAG_NOTE)
    return receipt


async def handle_profile_status(ctx: MemoryContext, args: argparse.Namespace) -> Receipt:
    """Report sanitized profile status without printing private contact values."""

    user_id = str(args.user_id)
    receipt = _new_receipt("profile.status", user_id)
    redactor = Redactor()
    try:
        stored = await ctx.provider.get_user_memory(
            user_id,
            "profile",
            page=1,
            page_size=_PROFILE_PAGE_SIZE,
        )
    except EverOSProviderError as error:
        if error.status_code != 404:
            raise
        receipt.data = _profile_status_data(
            profiles=[],
            record_ids=[],
            items=[],
            provider_status_code=404,
            redactor=redactor,
        )
        receipt.add_note("EverOS holds no profile memory for this user (provider status 404).")
        receipt.add_note(_PROFILE_PRIVACY_NOTE)
        return receipt

    profiles = _provider_records(stored.data, "profiles")
    receipt.data = _profile_status_data(
        profiles=profiles,
        record_ids=_provider_record_ids(stored.data, "profiles"),
        items=_collect_profile_items(profiles),
        provider_status_code=None,
        redactor=redactor,
    )
    receipt.redaction_count = redactor.count
    if not profiles:
        receipt.add_note("EverOS returned no profile record for this user.")
    receipt.add_note(_PROFILE_PRIVACY_NOTE)
    receipt.add_note(
        "Profile writes are not exposed by this tool; reviewed setup changes go through the "
        "authorized setup path."
    )
    return receipt


async def handle_upload(ctx: MemoryContext, args: argparse.Namespace) -> Receipt:
    """Upload one explicitly reviewed document; --reviewed is mandatory."""

    user_id = str(args.user_id)
    receipt = _new_receipt("upload.reviewed", user_id)
    redactor = Redactor()
    if not bool(args.reviewed):
        raise _Refusal(
            "Refusing to upload: pass --reviewed to confirm the caregiver reviewed this "
            "document before it reaches EverOS.",
            code="reviewed_flag_required",
        )
    path, content_type, size_bytes = _validated_upload_file(str(args.file))
    # The file is hashed for evidence only. Its content is never printed, logged,
    # or copied into the receipt.
    digest = _file_digest(path)
    uploaded = await ctx.adapter.upload_reviewed(path, user_id)
    object_key = uploaded.get("object_key") if isinstance(uploaded, Mapping) else None
    indexing_status = uploaded.get("indexing_status") if isinstance(uploaded, Mapping) else None
    if not isinstance(object_key, str) or not object_key:
        raise _InvalidProviderData(
            "EverOS did not return an upload object key, so no upload can be claimed.",
            code="missing_object_key",
        )

    receipt.data = {
        "file_name": redactor.text(path.name),
        "content_type": content_type,
        "size_bytes": size_bytes,
        "sha256": digest,
        "reviewed": True,
        "provider_object_key": object_key,
        "indexing_status": indexing_status,
        "provider_object_created": True,
        "memory_extracted": False,
    }
    receipt.redaction_count = redactor.count
    receipt.memory_changed = False
    receipt.add_note(
        "Document content was neither printed nor written to this receipt; only its size and "
        "SHA-256 digest are recorded."
    )
    receipt.add_note(
        f"EverOS returned indexing_status {indexing_status!r} exactly as shown. No memory fact "
        "was extracted by this command."
    )
    if indexing_status == "awaiting_memory_add":
        receipt.add_note(
            "A separate reviewed memory add is required before any extracted biller, account, "
            "amount, or due-date fact can be used."
        )
    return receipt


async def handle_skill_delete(ctx: MemoryContext, args: argparse.Namespace) -> Receipt:
    """Attempt selective skill deletion and report the provider limitation truthfully."""

    user_id = str(args.user_id)
    skill_id = str(args.skill_id)
    receipt = _new_receipt("skill.delete", user_id)
    redactor = Redactor()
    current = await _load_skill(ctx, user_id, skill_id)
    receipt.data = {
        "requested_skill_id": skill_id,
        "provider_skill_id": current.provider_skill_id,
        "skill_name": redactor.text(current.name, limit=_SKILL_NAME_LIMIT),
        "revision": current.revision,
        "skill_verified_before_attempt": True,
    }
    receipt.redaction_count = redactor.count

    try:
        await ctx.adapter.delete_skill(user_id, skill_id)
    except EverOSProviderError as error:
        if error.code is not EverOSErrorCode.UNSUPPORTED:
            raise
        _apply_provider_limitation(receipt, error)
        receipt.add_note("No EverOS memory was deleted or modified by this command.")
        receipt.add_note(_NO_WHOLE_SCOPE_DELETE_NOTE)
        return receipt

    receipt.memory_changed = True
    receipt.add_note("EverOS reported that the selective skill deletion succeeded.")
    receipt.add_note(_NO_WHOLE_SCOPE_DELETE_NOTE)
    return receipt


async def handle_skill_revise(ctx: MemoryContext, args: argparse.Namespace) -> Receipt:
    """Validate an immutable skill revision locally and report what EverOS can store."""

    user_id = str(args.user_id)
    skill_id = str(args.skill_id)
    receipt = _new_receipt("skill.revise", user_id)
    redactor = Redactor()
    reason = _validated_reason(args.reason)
    new_name = _validated_optional_name(args.set_name)
    edits = _parse_instruction_edits(args.set_instruction or [])
    if new_name is None and not edits:
        raise _Refusal(
            "Refusing to revise: pass --set-name or at least one --set-instruction so the "
            "revision changes something.",
            code="no_change_requested",
        )

    current = await _load_skill(ctx, user_id, skill_id)
    expected_revision = int(args.expected_revision)
    if current.revision != expected_revision:
        raise _Refusal(
            f"Refusing to revise: --expected-revision {expected_revision} is stale because "
            f"EverOS holds revision {current.revision}.",
            code="stale_revision",
            details={
                "source_skill_id": skill_id,
                "expected_revision": expected_revision,
                "current_revision": current.revision,
            },
        )
    known_step_ids = {step.step_id for step in current.steps}
    unknown = sorted(str(step_id) for step_id in edits if step_id not in known_step_ids)
    if unknown:
        raise _Refusal(
            "Refusing to revise: these step IDs are not in the stored skill: "
            + ", ".join(unknown),
            code="unknown_step_id",
            details={"source_skill_id": skill_id, "unknown_step_ids": unknown},
        )

    revised_steps = [
        step.model_copy(update={"instruction": edits.get(step.step_id, step.instruction)})
        for step in current.steps
    ]
    changed_fields = _changed_fields(current, revised_steps, new_name)
    if not changed_fields:
        raise _Refusal(
            "Refusing to revise: the requested edit matches the stored skill exactly.",
            code="no_effective_change",
            details={"source_skill_id": skill_id, "current_revision": current.revision},
        )

    payload = current.model_dump(mode="json")
    payload.update(
        {
            "revision": current.revision + 1,
            "name": new_name if new_name is not None else current.name,
            "steps": [step.model_dump(mode="json") for step in revised_steps],
            "provider_skill_id": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    try:
        proposed = SkillDocument.model_validate(payload)
    except ValidationError as error:
        raise _Refusal(
            "Refusing to revise: the proposed revision failed WebAccessible skill validation "
            "for: " + ", ".join(_error_locations(error)),
            code="invalid_revision",
        ) from error

    displayed = _redacted_skill(proposed, redactor)
    receipt.data = {
        "source_skill_id": skill_id,
        "provider_skill_id": current.provider_skill_id,
        "current_revision": current.revision,
        "proposed_revision": proposed.revision,
        "reason": redactor.text(reason, limit=_REVISION_REASON_LIMIT),
        "changed_fields": changed_fields,
        "proposed_skill_validated": True,
        "proposed_skill": displayed.model_dump(mode="json"),
        "proposed_markdown": render_skill_markdown(displayed),
    }
    receipt.redaction_count = redactor.count

    try:
        saved_value = await ctx.adapter.save_skill_revision(user_id, skill_id, proposed, reason)
    except EverOSProviderError as error:
        if error.code is not EverOSErrorCode.UNSUPPORTED:
            raise
        _apply_provider_limitation(receipt, error)
        receipt.add_note(
            "The proposed revision was validated locally and was not written, so the source "
            "revision remains the only evidence of the recorded run."
        )
        receipt.add_note(
            "No EverOS memory was changed by this command and the source skill was not "
            "overwritten or deleted."
        )
        return receipt

    try:
        saved = SkillDocument.model_validate(saved_value)
    except ValidationError as error:
        raise _InvalidProviderData(
            "EverOS returned a skill revision that failed WebAccessible validation.",
            code="invalid_saved_revision",
        ) from error
    if (
        saved.skill_key != current.skill_key
        or saved.revision != current.revision + 1
        or saved.source_session_id != current.source_session_id
    ):
        raise _InvalidProviderData(
            "EverOS returned a skill revision that does not match the source skill key, "
            "revision, or session, so it is not treated as the saved revision.",
            code="mismatched_saved_revision",
        )

    saved_display = _redacted_skill(saved, redactor)
    receipt.data["saved_provider_skill_id"] = saved.provider_skill_id
    receipt.data["saved_skill"] = saved_display.model_dump(mode="json")
    receipt.data["markdown"] = render_skill_markdown(saved_display)
    receipt.redaction_count = redactor.count
    receipt.memory_changed = True
    receipt.add_note("EverOS reported that the immutable skill revision was stored.")
    return receipt


async def _load_skill(ctx: MemoryContext, user_id: str, skill_id: str) -> SkillDocument:
    """Resolve one exact provider skill ID with no fuzzy fallback."""

    try:
        return await ctx.adapter.get_skill(user_id, skill_id)
    except KeyError as error:
        raise _NotFound(
            f"EverOS returned no agent_skill with ID {skill_id!r} for this user. No other "
            "skill was substituted.",
            code="skill_not_found",
            details={"requested_skill_id": skill_id},
        ) from error
    except (TypeError, ValueError, yaml.YAMLError) as error:
        raise _InvalidProviderData(
            "EverOS returned skill content that is not a valid WebAccessible skill "
            "document. Nothing was changed and no skill was reconstructed.",
            code="invalid_skill_content",
            details={"requested_skill_id": skill_id},
        ) from error


def _redacted_skill(skill: SkillDocument, redactor: Redactor) -> SkillDocument:
    """Redact prose fields only; IDs, selectors, origins, and URLs stay exact."""

    steps = [
        step.model_copy(
            update={
                "instruction": redactor.text(step.instruction, limit=_STEP_INSTRUCTION_LIMIT),
                "irreversible_description": redactor.optional(
                    step.irreversible_description,
                    limit=_IRREVERSIBLE_DESCRIPTION_LIMIT,
                ),
            }
        )
        for step in skill.steps
    ]
    candidate = skill.model_copy(
        update={
            "name": redactor.text(skill.name, limit=_SKILL_NAME_LIMIT),
            "steps": steps,
        }
    )
    return SkillDocument.model_validate(candidate.model_dump(mode="json"))


def _changed_fields(
    current: SkillDocument,
    revised_steps: Sequence[SkillStep],
    new_name: str | None,
) -> list[str]:
    changed: list[str] = []
    if new_name is not None and new_name != current.name:
        changed.append("name")
    for index, (original, revised) in enumerate(zip(current.steps, revised_steps, strict=True)):
        if original.instruction != revised.instruction:
            changed.append(f"steps[{index}].instruction")
    return changed


def _apply_provider_limitation(receipt: Receipt, error: EverOSProviderError) -> None:
    """Record an unsupported provider operation without claiming any change."""

    receipt.status = ReceiptStatus.UNSUPPORTED
    receipt.exit_code = ExitCode.PROVIDER_LIMITATION
    receipt.provider_limitation = str(error)
    receipt.memory_changed = False
    receipt.error = ReceiptError(
        code=error.code.value,
        message=str(error),
        retryable=error.retryable,
        provider_status_code=error.status_code,
    )


def _episode_record(item: Mapping[str, Any], redactor: Redactor) -> dict[str, Any]:
    """Build one episode record from an allowlist of safe fields."""

    record: dict[str, Any] = {"provider_episode_id": None}
    shown: set[str] = set()
    for name in _EPISODE_SCALAR_FIELDS:
        if name not in item:
            continue
        value = item[name]
        if value is not None and not isinstance(value, (str, int, float, bool)):
            continue
        shown.add(name)
        if name == "id":
            record["provider_episode_id"] = value
        else:
            record[name] = value
    summary: str | None = None
    for name in _EPISODE_PROSE_FIELDS:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            shown.add(name)
            summary = redactor.text(value)
            break
    record["summary"] = summary
    record["fields_not_shown"] = sorted(str(key) for key in item if str(key) not in shown)
    return record


def _profile_status_data(
    *,
    profiles: Sequence[Mapping[str, Any]],
    record_ids: Sequence[str],
    items: Sequence[Mapping[str, Any]],
    provider_status_code: int | None,
    redactor: Redactor,
) -> dict[str, Any]:
    by_category: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        category = item.get("category")
        if isinstance(category, str):
            by_category.setdefault(category, []).append(item)

    setup_fields: list[dict[str, Any]] = []
    caregiver_stored = False
    for field_name, category in _SETUP_PROFILE_CATEGORIES.items():
        entries = by_category.pop(category, [])
        withheld = _is_private_profile_field(field_name, entries)
        value: str | None = None
        if entries and not withheld:
            value = redactor.optional(_optional_str(entries[0].get("description")))
        if field_name in _PRIVATE_PROFILE_FIELDS:
            caregiver_stored = bool(entries)
        setup_fields.append(
            {
                "field": field_name,
                "category": category,
                "present": bool(entries),
                "item_count": len(entries),
                "item_ids": _profile_item_ids(entries),
                "classification": _profile_classification(entries),
                "value": value,
                "value_withheld": withheld,
            }
        )

    other_categories = [
        {
            "category": category,
            "item_count": len(entries),
            "item_ids": _profile_item_ids(entries),
            "values_withheld": True,
        }
        for category, entries in sorted(by_category.items())
    ]
    return {
        "user_memory_type": "profile",
        "profile_present": bool(profiles),
        "profile_record_count": len(profiles),
        "profile_record_ids": list(record_ids),
        "provider_status_code": provider_status_code,
        "caregiver_mobile_stored": caregiver_stored,
        "setup_fields": setup_fields,
        "other_categories": other_categories,
    }


def _collect_profile_items(profiles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collect every categorized profile item, including categories this tool does not name."""

    collected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            category = value.get("category")
            item_id = value.get("item_id") or value.get("id")
            if isinstance(category, str) and isinstance(item_id, str) and item_id not in seen:
                seen.add(item_id)
                collected.append({str(key): item for key, item in value.items()})
            for nested in value.values():
                visit(nested)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for nested in value:
                visit(nested)

    for profile in profiles:
        visit(profile.get("profile_data"))
    return collected


def _is_private_profile_field(field_name: str, entries: Sequence[Mapping[str, Any]]) -> bool:
    if field_name in _PRIVATE_PROFILE_FIELDS:
        return True
    for entry in entries:
        metadata = entry.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        if str(metadata.get("classification") or "") in _PRIVATE_CLASSIFICATIONS:
            return True
        if str(metadata.get("allowed_use") or "") in _PRIVATE_ALLOWED_USES:
            return True
    return False


def _profile_classification(entries: Sequence[Mapping[str, Any]]) -> str | None:
    for entry in entries:
        metadata = entry.get("metadata")
        if isinstance(metadata, Mapping):
            classification = metadata.get("classification")
            if isinstance(classification, str) and classification:
                return classification
    return None


def _profile_item_ids(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    ids: list[str] = []
    for entry in entries:
        value = entry.get("item_id") or entry.get("id")
        if isinstance(value, str) and value.strip():
            ids.append(value)
    return ids


def _provider_records(data: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [
        {str(name): item for name, item in record.items()}
        for record in value
        if isinstance(record, Mapping)
    ]


def _provider_record_ids(data: Mapping[str, Any], key: str) -> list[str]:
    """Return provider record IDs exactly as EverOS returned them."""

    ids: list[str] = []
    for record in _provider_records(data, key):
        value = record.get("id")
        if isinstance(value, str) and value.strip():
            ids.append(value)
    return ids


def _file_digest(path: Path) -> str:
    """Hash a reviewed document without printing or retaining its content."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_user_id(value: str) -> str:
    if value != value.strip() or _USER_ID_PATTERN.match(value) is None:
        raise _Refusal(
            "Refusing to run: --user-id must be the exact WebAccessible user ID, 1-96 "
            "characters from A-Z, a-z, 0-9, ':', '_', and '-', with no surrounding whitespace.",
            code="invalid_user_id",
        )
    return value


def _validated_skill_id(value: str) -> str:
    invalid = (
        value != value.strip()
        or not 1 <= len(value) <= _SKILL_ID_MAX_LENGTH
        or any(character.isspace() for character in value)
        or any(character in _WILDCARD_CHARACTERS for character in value)
    )
    if invalid:
        raise _Refusal(
            "Refusing to run: --skill-id must be the exact EverOS provider skill ID. "
            "Prefixes, wildcards, and whitespace are not accepted.",
            code="invalid_skill_id",
        )
    return value


def _validated_query(value: str) -> str:
    if not value.strip() or len(value) > _MAX_QUERY_LENGTH:
        raise _Refusal(
            f"Refusing to search: --query must contain 1-{_MAX_QUERY_LENGTH} characters.",
            code="invalid_query",
        )
    return value


def _validated_top_k(value: int) -> int:
    if not 1 <= int(value) <= _MAX_TOP_K:
        raise _Refusal(
            f"Refusing to search: --top-k must be between 1 and {_MAX_TOP_K}.",
            code="invalid_top_k",
        )
    return int(value)


def _validated_reason(value: str) -> str:
    reason = value.strip()
    if not 1 <= len(reason) <= _REVISION_REASON_LIMIT:
        raise _Refusal(
            f"Refusing to revise: --reason must contain 1-{_REVISION_REASON_LIMIT} characters.",
            code="invalid_reason",
        )
    return reason


def _validated_optional_name(value: str | None) -> str | None:
    if value is None:
        return None
    name = value.strip()
    if not 1 <= len(name) <= _SKILL_NAME_LIMIT:
        raise _Refusal(
            f"Refusing to revise: --set-name must contain 1-{_SKILL_NAME_LIMIT} characters.",
            code="invalid_name",
        )
    return name


def _parse_instruction_edits(values: Sequence[str]) -> dict[UUID, str]:
    edits: dict[UUID, str] = {}
    for raw in values:
        step_text, separator, instruction_text = raw.partition("=")
        if not separator:
            raise _Refusal(
                "Refusing to revise: --set-instruction must be given as STEP_ID=INSTRUCTION.",
                code="invalid_instruction_edit",
            )
        try:
            step_id = UUID(step_text.strip())
        except ValueError as error:
            raise _Refusal(
                "Refusing to revise: --set-instruction requires the exact step UUID printed by "
                "'skill show'.",
                code="invalid_step_id",
            ) from error
        instruction = instruction_text.strip()
        if not 1 <= len(instruction) <= _STEP_INSTRUCTION_LIMIT:
            raise _Refusal(
                "Refusing to revise: each instruction must contain 1-"
                f"{_STEP_INSTRUCTION_LIMIT} characters.",
                code="invalid_instruction",
            )
        if step_id in edits:
            raise _Refusal(
                "Refusing to revise: each step ID may be edited only once.",
                code="duplicate_step_id",
            )
        edits[step_id] = instruction
    return edits


def _validated_upload_file(raw: str) -> tuple[Path, str, int]:
    path = Path(raw).expanduser()
    if not path.is_file():
        raise _Refusal(
            "Refusing to upload: --file must point to an existing file.",
            code="missing_file",
        )
    content_type = _UPLOAD_CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        allowed = ", ".join(sorted(_UPLOAD_CONTENT_TYPES))
        raise _Refusal(
            f"Refusing to upload: reviewed documents must use one of {allowed}.",
            code="unsupported_file_type",
        )
    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise _Refusal("Refusing to upload: the file is empty.", code="empty_file")
    if size_bytes > _MAX_UPLOAD_BYTES:
        raise _Refusal(
            f"Refusing to upload: reviewed documents are limited to {_MAX_UPLOAD_BYTES} bytes.",
            code="file_too_large",
        )
    return path, content_type, size_bytes


def _error_locations(error: ValidationError) -> list[str]:
    locations: set[str] = set()
    for item in error.errors():
        location = ".".join(str(part) for part in item.get("loc", ()))
        locations.add(location or "document")
    return sorted(locations)


def _reason(error: OSError) -> str:
    """Describe a local filesystem failure without leaking anything else."""

    return error.strerror or type(error).__name__


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _new_receipt(command: str, user_id: str | None) -> Receipt:
    scope = EverOSProvider.agent_id_for(user_id) if user_id else None
    return Receipt(command=command, user_id=user_id, agent_memory_scope=scope)


def _command_error_receipt(command: str, user_id: str | None, error: _CommandError) -> Receipt:
    receipt = _new_receipt(command, user_id)
    receipt.status = error.status
    receipt.exit_code = error.exit_code
    receipt.memory_changed = False
    receipt.error = ReceiptError(
        code=error.code,
        message=error.message,
        retryable=error.retryable,
    )
    receipt.data = dict(error.details)
    return receipt


def _provider_error_receipt(
    command: str,
    user_id: str | None,
    error: EverOSProviderError,
) -> Receipt:
    receipt = _new_receipt(command, user_id)
    receipt.memory_changed = False
    if error.code is EverOSErrorCode.UNSUPPORTED:
        _apply_provider_limitation(receipt, error)
        receipt.add_note(_NO_WHOLE_SCOPE_DELETE_NOTE)
        return receipt
    if error.code is EverOSErrorCode.UNCONFIGURED:
        receipt.status = ReceiptStatus.UNCONFIGURED
        receipt.exit_code = ExitCode.UNCONFIGURED
    else:
        receipt.status = ReceiptStatus.UNAVAILABLE
        receipt.exit_code = ExitCode.PROVIDER_UNAVAILABLE
        receipt.add_note(_UNAVAILABLE_NOTE)
    receipt.error = ReceiptError(
        code=error.code.value,
        message=str(error),
        retryable=error.retryable,
        provider_status_code=error.status_code,
    )
    return receipt


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--user-id",
        required=True,
        metavar="USER_ID",
        help="Exact WebAccessible user ID; no prefix, wildcard, or fuzzy matching.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="stdout format (default: text). 'json' prints the machine-readable receipt.",
    )
    parser.add_argument(
        "--receipt",
        metavar="PATH",
        default=None,
        help="Also write the machine-readable JSON receipt to PATH.",
    )


def _add_skill_id_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skill-id",
        required=True,
        metavar="SKILL_ID",
        help="Exact EverOS provider skill ID as printed by 'routines list'.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the caregiver CLI parser."""

    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Inspect and administer the EverOS memory WebAccessible holds for one "
            "participant, using the live EverOS ownership adapter."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    groups = parser.add_subparsers(dest="group", required=True, metavar="GROUP")

    routines = groups.add_parser(
        "routines",
        help="Read the agent-owned routine list.",
        description="Read the agent-owned routine list.",
    ).add_subparsers(dest="command", required=True, metavar="COMMAND")
    routines_list = routines.add_parser(
        "list",
        help="List the validated routines EverOS holds for one user.",
        description=(
            "List validated routines from agent-owned agent_skill memory. Records that do not "
            "validate against the WebAccessible skill contract are reported by provider ID "
            "only, never replaced."
        ),
    )
    _add_common_arguments(routines_list)
    routines_list.set_defaults(handler=handle_routines_list, command_name="routines.list")

    skill = groups.add_parser(
        "skill",
        help="Inspect or attempt to administer one exact skill.",
        description="Inspect or attempt to administer one exact skill.",
    ).add_subparsers(dest="command", required=True, metavar="COMMAND")

    skill_show = skill.add_parser(
        "show",
        help="Show one validated skill as Markdown or structured JSON.",
        description=(
            "Show one validated skill. Text output is readable Markdown whose YAML front "
            "matter is the canonical machine-readable route; --format json returns the "
            "validated structured document plus the same Markdown."
        ),
    )
    _add_common_arguments(skill_show)
    _add_skill_id_argument(skill_show)
    skill_show.set_defaults(handler=handle_skill_show, command_name="skill.show")

    skill_delete = skill.add_parser(
        "delete",
        help="Attempt selective skill deletion (reports the provider limitation).",
        description=(
            "Attempt to delete one exact skill. The installed EverOS SDK exposes no selective "
            "agent-skill deletion, so this command reports the provider limitation and exits "
            "3. It never falls back to deleting all user or agent memory."
        ),
    )
    _add_common_arguments(skill_delete)
    _add_skill_id_argument(skill_delete)
    skill_delete.set_defaults(handler=handle_skill_delete, command_name="skill.delete")

    skill_revise = skill.add_parser(
        "revise",
        help="Validate an immutable skill revision (reports the provider limitation).",
        description=(
            "Validate a new immutable revision of one exact skill locally, then attempt the "
            "provider write. The installed EverOS SDK cannot create an immutable revision "
            "without risking the source skill, so this command reports the provider "
            "limitation and exits 3 with the validated proposal attached."
        ),
    )
    _add_common_arguments(skill_revise)
    _add_skill_id_argument(skill_revise)
    skill_revise.add_argument(
        "--expected-revision",
        required=True,
        type=int,
        metavar="N",
        help="Revision the caregiver reviewed; a stale value is refused.",
    )
    skill_revise.add_argument(
        "--reason",
        required=True,
        metavar="TEXT",
        help=f"Audit reason for the revision (1-{_REVISION_REASON_LIMIT} characters).",
    )
    skill_revise.add_argument(
        "--set-name",
        default=None,
        metavar="TEXT",
        help="Replacement routine name.",
    )
    skill_revise.add_argument(
        "--set-instruction",
        action="append",
        default=None,
        metavar="STEP_ID=INSTRUCTION",
        help="Replacement instruction for one exact stored step UUID; repeatable.",
    )
    skill_revise.set_defaults(handler=handle_skill_revise, command_name="skill.revise")

    episodes = groups.add_parser(
        "episodes",
        help="Search user-owned completion memory.",
        description="Search user-owned completion memory.",
    ).add_subparsers(dest="command", required=True, metavar="COMMAND")
    episodes_search = episodes.add_parser(
        "search",
        help="Search completion episodes for one user.",
        description=(
            "Search user-owned episode memory. Provider episode IDs, timestamps, and indexing "
            "status are printed exactly as returned, and no completion answer is inferred "
            "when memory has none."
        ),
    )
    _add_common_arguments(episodes_search)
    episodes_search.add_argument(
        "--query",
        required=True,
        metavar="TEXT",
        help="Caregiver phrasing to search for.",
    )
    episodes_search.add_argument(
        "--top-k",
        type=int,
        default=10,
        metavar="N",
        help=f"Maximum matches to request from EverOS, 1-{_MAX_TOP_K} (default: 10).",
    )
    episodes_search.set_defaults(handler=handle_episodes_search, command_name="episodes.search")

    profile = groups.add_parser(
        "profile",
        help="Inspect sanitized user-owned profile status.",
        description="Inspect sanitized user-owned profile status.",
    ).add_subparsers(dest="command", required=True, metavar="COMMAND")
    profile_status = profile.add_parser(
        "status",
        help="Report which reviewed setup fields EverOS holds.",
        description=(
            "Report which reviewed setup fields EverOS holds for one user. Values are shown "
            "only for reviewed non-private categories; caregiver contact values are never "
            "printed. This command performs no profile write."
        ),
    )
    _add_common_arguments(profile_status)
    profile_status.set_defaults(handler=handle_profile_status, command_name="profile.status")

    upload = groups.add_parser(
        "upload",
        help="Upload one explicitly reviewed document.",
        description=(
            "Upload one explicitly reviewed document to EverOS. --reviewed is mandatory. The "
            "document content is never printed; only its name, size, and SHA-256 digest are "
            "recorded, together with the provider object key and indexing status exactly as "
            "returned."
        ),
    )
    _add_common_arguments(upload)
    upload.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="Path to the reviewed PDF or image.",
    )
    upload.add_argument(
        "--reviewed",
        action="store_true",
        help="Required confirmation that a caregiver reviewed this document.",
    )
    upload.set_defaults(handler=handle_upload, command_name="upload.reviewed")

    return parser


def _write_receipt_file(path: Path, receipt: Receipt) -> bool:
    try:
        path.write_text(render_receipt_json(receipt), encoding="utf-8")
    except OSError as error:
        sys.stderr.write(
            f"{TOOL_NAME}: could not write the receipt to {str(path)!r}: {_reason(error)}\n"
        )
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run one caregiver memory command and return its exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    command: str = str(args.command_name)
    handler: _Handler = args.handler
    user_id: str | None = None
    receipt: Receipt

    try:
        user_id = _validated_user_id(str(args.user_id))
        args.user_id = user_id
        raw_skill_id = getattr(args, "skill_id", None)
        if raw_skill_id is not None:
            args.skill_id = _validated_skill_id(str(raw_skill_id))
        settings = get_settings()
        context = MemoryContext(
            adapter=EverOSAdapter(settings),
            provider=EverOSProvider(settings),
        )
        receipt = asyncio.run(handler(context, args))
    except _CommandError as error:
        receipt = _command_error_receipt(command, user_id, error)
    except EverOSProviderError as error:
        receipt = _provider_error_receipt(command, user_id, error)
    except ValidationError:
        receipt = _command_error_receipt(
            command,
            user_id,
            _InvalidProviderData(
                "EverOS returned memory content that failed WebAccessible validation.",
                code="invalid_provider_data",
            ),
        )
    except ValueError as error:
        receipt = _command_error_receipt(
            command,
            user_id,
            _Refusal(str(error), code="invalid_request"),
        )
    except OSError as error:
        receipt = _command_error_receipt(
            command,
            user_id,
            _Refusal(
                f"The command could not read local input: {_reason(error)}.",
                code="local_io_error",
            ),
        )
    except Exception as error:
        # Only the exception class is reported. Raw provider detail could carry a
        # request body or credential, so it is never printed or written down.
        receipt = _command_error_receipt(
            command,
            user_id,
            _UnexpectedFailure(
                f"An unexpected {type(error).__name__} stopped the command; no provider "
                "detail is printed and no memory claim is made.",
            ),
        )

    if str(args.format) == "json":
        sys.stdout.write(render_receipt_json(receipt))
    else:
        stream = sys.stdout if receipt.status is ReceiptStatus.OK else sys.stderr
        stream.write(render_text(receipt))

    exit_code = int(receipt.exit_code)
    receipt_path = getattr(args, "receipt", None)
    if receipt_path is not None and not _write_receipt_file(Path(str(receipt_path)), receipt):
        exit_code = exit_code or int(ExitCode.REFUSED)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
