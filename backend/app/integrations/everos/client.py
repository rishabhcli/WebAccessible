"""EverOS ownership adapter for live persistent user and agent memory."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import yaml
from everos_cloud.client import EverOS, EverOSAPIError, EverOSError, EverOSStorageError
from everos_cloud.models.edit_input_operations_inner import EditInputOperationsInner

from backend.app.config import Settings
from backend.app.contracts.models import EpisodeAnswer, RoutineSummary, SkillDocument

_USER_MEMORY_TYPES: Final = frozenset({"profile", "atomic_fact", "episode", "foresight"})
_AGENT_MEMORY_TYPES: Final = frozenset({"agent_case", "agent_skill"})
_SETUP_PROFILE_CATEGORIES: Final = {
    "participant_name": "webaccessible.participant_name",
    "reading_size": "webaccessible.reading_size",
    "voice_enabled": "webaccessible.voice_enabled",
    "timezone": "webaccessible.timezone",
    "caregiver_mobile": "webaccessible.caregiver_mobile",
}
_PROFILE_PREFERENCE_FIELDS: Final = frozenset({"reading_size", "voice_enabled", "timezone"})
_MEMORY_RETRIEVAL_DELAYS_SECONDS: Final = (0.0, 1.0, 2.0, 4.0, 8.0)
_PRIVATE_VALUE_REMOVED: Final = object()


class EverOSErrorCode(StrEnum):
    UNCONFIGURED = "unconfigured"
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    INDEXING = "indexing"
    WRITE_FAILED = "write_failed"
    UNSUPPORTED = "unsupported"


class EverOSProviderError(RuntimeError):
    """A sanitized live-memory failure suitable for readiness state."""

    def __init__(
        self,
        code: EverOSErrorCode,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class EverOSResult:
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EverOSSearchResult:
    user_memory: dict[str, Any]
    agent_memory: dict[str, Any]


class EverOSProvider:
    """Translate a WebAccessible user into EverOS user-owned and agent-owned scopes."""

    __slots__ = ("_api_key", "_app_id", "_host", "_project_id", "_timeout")

    def __init__(self, settings: Settings) -> None:
        if settings.everos_api_key is None:
            raise EverOSProviderError(
                EverOSErrorCode.UNCONFIGURED,
                "EverOS is not configured.",
                retryable=False,
            )
        self._api_key = settings.everos_api_key.get_secret_value()
        self._host = settings.everos_host
        self._app_id = settings.everos_app_id
        self._project_id = settings.everos_project_id
        self._timeout = settings.everos_timeout_seconds

    @staticmethod
    def agent_id_for(user_id: str) -> str:
        user_id = _require_identifier("user_id", user_id)
        return f"webaccessible:{user_id}"

    async def search(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 10,
        include_profile: bool = True,
    ) -> EverOSSearchResult:
        """Search both ownership scopes without allowing either to replace the other."""

        user_id = _require_identifier("user_id", user_id)
        query = _require_identifier("query", query)
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        agent_id = self.agent_id_for(user_id)
        user_result, agent_result = await asyncio.gather(
            self._call(
                "search",
                query,
                user_id=user_id,
                method="hybrid",
                top_k=top_k,
                include_profile=include_profile,
            ),
            self._call(
                "search",
                query,
                agent_id=agent_id,
                method="hybrid",
                top_k=top_k,
            ),
        )
        return EverOSSearchResult(
            user_memory=_without_private_contact(_as_plain_dict(user_result)),
            agent_memory=_as_plain_dict(agent_result),
        )

    async def get_user_memory(
        self,
        user_id: str,
        memory_type: str,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: Mapping[str, Any] | None = None,
    ) -> EverOSResult:
        user_id = _require_identifier("user_id", user_id)
        if memory_type not in _USER_MEMORY_TYPES:
            raise ValueError(f"{memory_type!r} is not a user-owned memory type")
        result = await self._call(
            "get",
            memory_type,
            user_id=user_id,
            page=page,
            page_size=page_size,
            filters=dict(filters) if filters is not None else None,
        )
        return EverOSResult(_as_plain_dict(result))

    async def get_agent_memory(
        self,
        user_id: str,
        memory_type: str,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: Mapping[str, Any] | None = None,
    ) -> EverOSResult:
        if memory_type not in _AGENT_MEMORY_TYPES:
            raise ValueError(f"{memory_type!r} is not an agent-owned memory type")
        result = await self._call(
            "get",
            memory_type,
            agent_id=self.agent_id_for(user_id),
            page=page,
            page_size=page_size,
            filters=dict(filters) if filters is not None else None,
        )
        return EverOSResult(_as_plain_dict(result))

    async def add(
        self,
        session_id: str,
        user_id: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        mode: str = "chat",
        async_mode: bool = False,
    ) -> EverOSResult:
        """Append sanitized task events to the live extraction session."""

        session_id = _require_identifier("session_id", session_id)
        user_id = _require_identifier("user_id", user_id)
        if not messages:
            raise ValueError("messages must not be empty")
        normalized = tuple(self._normalize_message(user_id, message) for message in messages)
        try:
            result = await self._call(
                "add",
                session_id,
                normalized,
                mode=mode,
                async_mode=async_mode,
            )
        except EverOSProviderError as exc:
            if exc.code not in {EverOSErrorCode.UNAUTHORIZED, EverOSErrorCode.RATE_LIMITED}:
                raise EverOSProviderError(
                    EverOSErrorCode.WRITE_FAILED,
                    "EverOS did not accept the memory events.",
                    retryable=exc.retryable,
                    status_code=exc.status_code,
                ) from exc
            raise
        return EverOSResult(_as_plain_dict(result))

    async def flush(self, session_id: str) -> EverOSResult:
        """Trigger the live Case/Skill/Episode extraction path."""

        session_id = _require_identifier("session_id", session_id)
        try:
            result = await self._call("flush", session_id)
        except EverOSProviderError as exc:
            if exc.code not in {EverOSErrorCode.UNAUTHORIZED, EverOSErrorCode.RATE_LIMITED}:
                raise EverOSProviderError(
                    EverOSErrorCode.WRITE_FAILED,
                    "EverOS did not flush the memory session.",
                    retryable=exc.retryable,
                    status_code=exc.status_code,
                ) from exc
            raise
        return EverOSResult(_as_plain_dict(result))

    async def edit_profile(
        self,
        user_id: str,
        operations: Sequence[Mapping[str, Any]],
    ) -> EverOSResult:
        user_id = _require_identifier("user_id", user_id)
        if not operations:
            raise ValueError("operations must not be empty")
        if len(operations) > 50:
            raise ValueError("EverOS accepts at most 50 profile operations")
        try:
            sdk_operations = tuple(
                EditInputOperationsInner.from_dict(dict(operation)) for operation in operations
            )
        except Exception:
            raise EverOSProviderError(
                EverOSErrorCode.INVALID_RESPONSE,
                "EverOS could not encode the reviewed profile update.",
                retryable=False,
            ) from None
        result = await self._call("edit", user_id, sdk_operations)
        return EverOSResult(_as_plain_dict(result))

    async def update_profile(
        self,
        user_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Upsert reviewed setup preferences in user-owned EverOS profile memory.

        The returned receipt deliberately contains no profile values. In particular,
        caregiver contact metadata remains inside EverOS and cannot flow into logs or
        Snowflake through the application-facing result.
        """

        user_id = _require_identifier("user_id", user_id)
        normalized = _normalize_setup_profile(data)
        try:
            current = await self.get_user_memory(user_id, "profile", page=1, page_size=20)
        except EverOSProviderError as exc:
            if exc.status_code != 404:
                raise
            profiles: list[dict[str, Any]] = []
        else:
            profiles = _items(current.data, "profiles")
        if not profiles:
            profiles = await self._bootstrap_profile(user_id, normalized)
        profile_id = _first_text(item.get("id") for item in profiles)
        existing = _profile_items_by_category(profiles)
        operations, updated_fields, removed_fields = _profile_edit_operations(
            normalized,
            existing,
        )
        caregiver_category = _SETUP_PROFILE_CATEGORIES["caregiver_mobile"]
        caregiver_stored = bool(existing.get(caregiver_category))
        if "caregiver_mobile" in normalized:
            caregiver_stored = normalized["caregiver_mobile"] is not None

        if not operations:
            return {
                "user_id": user_id,
                "profile_id": profile_id,
                "status": "unchanged",
                "version": None,
                "applied": 0,
                "updated_fields": [],
                "removed_fields": [],
                "caregiver_mobile_stored": caregiver_stored,
            }

        edited = await self.edit_profile(user_id, operations)
        applied = _optional_int(edited.data.get("applied"))
        version = _optional_int(edited.data.get("version"))
        if applied is None:
            applied = len(operations)
        if applied == len(operations):
            status = "updated"
        elif applied > 0:
            status = "partial"
        else:
            status = "unchanged"
        return {
            "user_id": user_id,
            "profile_id": profile_id,
            "status": status,
            "version": version,
            "applied": applied,
            "updated_fields": updated_fields,
            "removed_fields": removed_fields,
            "caregiver_mobile_stored": caregiver_stored,
        }

    async def _bootstrap_profile(
        self,
        user_id: str,
        data: Mapping[str, str | bool | None],
    ) -> list[dict[str, Any]]:
        """Create the extracted profile required by EverOS before its edit API can run."""

        reviewed_preferences = {
            key: value for key, value in data.items() if key != "caregiver_mobile"
        }
        await self.add(
            f"webaccessible-setup:{user_id}",
            user_id,
            (
                {
                    "role": "user",
                    "content": (
                        "Reviewed WebAccessible participant setup. Remember these as stable "
                        "profile preferences: "
                        f"{json.dumps(reviewed_preferences, separators=(',', ':'), sort_keys=True)}"
                    ),
                },
            ),
            mode="chat",
            async_mode=False,
        )
        await self.flush(f"webaccessible-setup:{user_id}")

        for delay_seconds in _MEMORY_RETRIEVAL_DELAYS_SECONDS:
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            try:
                current = await self.get_user_memory(
                    user_id,
                    "profile",
                    page=1,
                    page_size=20,
                )
            except EverOSProviderError as exc:
                if exc.status_code == 404 or exc.retryable:
                    continue
                raise
            profiles = _items(current.data, "profiles")
            if profiles:
                return profiles

        raise EverOSProviderError(
            EverOSErrorCode.INDEXING,
            "EverOS accepted the setup but its participant profile is still indexing.",
            retryable=True,
        )

    async def delete_user_memory(self, user_id: str) -> EverOSResult:
        result = await self._call("delete", user_id=_require_identifier("user_id", user_id))
        return EverOSResult(_as_plain_dict(result))

    async def delete_agent_memory(self, user_id: str) -> EverOSResult:
        result = await self._call("delete", agent_id=self.agent_id_for(user_id))
        return EverOSResult(_as_plain_dict(result))

    async def delete_skill(self, user_id: str, skill_id: str) -> None:
        """Reject unsafe emulation of selective deletion on the installed SDK."""

        self.agent_id_for(user_id)
        _require_identifier("skill_id", skill_id)
        raise EverOSProviderError(
            EverOSErrorCode.UNSUPPORTED,
            "EverOS does not expose selective agent-skill deletion; no memory was deleted.",
            retryable=False,
        )

    async def save_skill_revision(
        self,
        user_id: str,
        source_skill_id: str,
        skill: SkillDocument,
        reason: str,
    ) -> SkillDocument:
        """Reject a revision write that EverOS cannot preserve immutably."""

        self.agent_id_for(user_id)
        _require_identifier("source_skill_id", source_skill_id)
        reason = reason.strip()
        if not reason or len(reason) > 160:
            raise ValueError("revision reason must contain between 1 and 160 characters")
        if skill.revision < 2:
            raise ValueError("a saved skill revision must have revision 2 or greater")
        raise EverOSProviderError(
            EverOSErrorCode.UNSUPPORTED,
            "EverOS cannot create an immutable agent-skill revision without risking the source "
            "skill; no memory was changed.",
            retryable=False,
        )

    async def delete_session_memory(self, session_id: str) -> EverOSResult:
        result = await self._call(
            "delete", session_id=_require_identifier("session_id", session_id)
        )
        return EverOSResult(_as_plain_dict(result))

    async def upload(self, path: str | Path) -> str:
        """Upload an explicitly reviewed file and return its provider object key."""

        upload_path = Path(path)
        if not upload_path.is_file():
            raise ValueError("upload path must be an existing file")
        result = await self._call("upload", str(upload_path))
        if not isinstance(result, str) or not result:
            raise EverOSProviderError(
                EverOSErrorCode.INVALID_RESPONSE,
                "EverOS did not return an upload object key.",
                retryable=False,
            )
        return result

    async def upload_reviewed(self, path: str | Path, user_id: str) -> dict[str, Any]:
        """Upload reviewed input without claiming that memory extraction has started."""

        user_id = _require_identifier("user_id", user_id)
        object_key = await self.upload(path)
        return {
            "user_id": user_id,
            "object_key": object_key,
            "indexing_status": "awaiting_memory_add",
        }

    async def _call(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        def invoke() -> Any:
            with EverOS(
                self._api_key,
                host=self._host,
                app_id=self._app_id,
                project_id=self._project_id,
                timeout=self._timeout,
            ) as client:
                return getattr(client, operation)(*args, **kwargs)

        try:
            return await asyncio.to_thread(invoke)
        except Exception as exc:
            raise _map_error(exc) from exc

    def _normalize_message(self, user_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        role = str(message.get("role", "user"))
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValueError("message role is not supported")
        content = message.get("content")
        if not isinstance(content, (str, list)):
            raise ValueError("message content must be text or typed content items")
        sender_id = self.agent_id_for(user_id) if role in {"assistant", "system"} else user_id
        normalized: dict[str, Any] = {
            "sender_id": sender_id,
            "sender_name": "WebAccessible" if role in {"assistant", "system"} else None,
            "role": role,
            "content": content,
        }
        if message.get("timestamp") is not None:
            normalized["timestamp"] = int(message["timestamp"])
        if message.get("tool_calls") is not None:
            normalized["tool_calls"] = message["tool_calls"]
        if message.get("tool_call_id") is not None:
            normalized["tool_call_id"] = message["tool_call_id"]
        return {key: value for key, value in normalized.items() if value is not None}


class EverOSAdapter:
    """Application-facing routines and completion-memory contract."""

    __slots__ = ("_provider",)

    def __init__(self, settings: Settings) -> None:
        self._provider = EverOSProvider(settings)

    async def update_profile(
        self,
        user_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        return await self._provider.update_profile(user_id, data)

    async def delete_skill(self, user_id: str, skill_id: str) -> None:
        await self._provider.delete_skill(user_id, skill_id)

    async def save_skill_revision(
        self,
        user_id: str,
        source_skill_id: str,
        skill: SkillDocument,
        reason: str,
    ) -> SkillDocument:
        return await self._provider.save_skill_revision(
            user_id,
            source_skill_id,
            skill,
            reason,
        )

    async def upload_reviewed(self, path: str | Path, user_id: str) -> dict[str, Any]:
        return await self._provider.upload_reviewed(path, user_id)

    async def list_routines(self, user_id: str) -> list[RoutineSummary]:
        result = await self._provider.get_agent_memory(
            user_id,
            "agent_skill",
            page=1,
            page_size=100,
        )
        return _routine_summaries(_items(result.data, "agent_skills"))

    async def search_routines(self, user_id: str, query: str) -> list[RoutineSummary]:
        result = await self._provider.search(user_id, query, top_k=20)
        return _routine_summaries(_items(result.agent_memory, "agent_skills"))

    async def get_skill(self, user_id: str, skill_id: str) -> SkillDocument:
        skill_id = _require_identifier("skill_id", skill_id)
        result = await self._provider.get_agent_memory(
            user_id,
            "agent_skill",
            page=1,
            page_size=100,
        )
        for item in _items(result.data, "agent_skills"):
            if str(item.get("id")) == skill_id:
                return _skill_document(item)
        raise KeyError(f"EverOS skill {skill_id!r} was not found for this user")

    async def save_teach_run(
        self,
        user_id: str,
        session_id: str,
        skill: SkillDocument | Mapping[str, Any],
        episode: Mapping[str, Any] | Any,
    ) -> dict[str, Any]:
        """Send the verified trajectory through EverOS add/flush extraction."""

        skill_document = (
            skill if isinstance(skill, SkillDocument) else SkillDocument.model_validate(skill)
        )
        markdown = _render_skill_markdown(skill_document)
        episode_payload = _as_plain(episode)
        timestamp_ms = int(datetime.now().timestamp() * 1000)
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"Teach the recurring task {skill_document.name}. The participant performed "
                    "every target-page action in Browserbase Live View."
                ),
                "timestamp": timestamp_ms,
            },
        ]
        for step_number, step in enumerate(skill_document.steps, start=1):
            observe_call_id = f"observe-{step.step_id}"
            verify_call_id = f"verify-{step.step_id}"
            messages.extend(
                (
                    {
                        "role": "assistant",
                        "content": "Observe the sanitized page and locate the next target.",
                        "tool_calls": [
                            {
                                "id": observe_call_id,
                                "type": "function",
                                "function": {
                                    "name": "observe_sanitized_page",
                                    "arguments": json.dumps(
                                        {
                                            "step_number": step_number,
                                            "preconditions": _as_plain(step.preconditions),
                                        },
                                        separators=(",", ":"),
                                        sort_keys=True,
                                    ),
                                },
                            }
                        ],
                        "timestamp": timestamp_ms + len(messages),
                    },
                    {
                        "role": "tool",
                        "content": json.dumps(
                            {
                                "instruction": step.instruction,
                                "selectors": _as_plain(step.selectors),
                                "target_visible": True,
                                "target_enabled": True,
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "tool_call_id": observe_call_id,
                        "timestamp": timestamp_ms + len(messages) + 1,
                    },
                    {
                        "role": "assistant",
                        "content": (
                            f"Guidance shown to the participant: {step.instruction} "
                            "The application waited for trusted participant input."
                        ),
                        "timestamp": timestamp_ms + len(messages) + 2,
                    },
                    {
                        "role": "user",
                        "content": (
                            "The participant performed the instructed action through Browserbase "
                            "Live View; WebAccessible did not click or submit for them."
                        ),
                        "timestamp": timestamp_ms + len(messages) + 3,
                    },
                    {
                        "role": "assistant",
                        "content": "Verify the trusted action against the recorded transition.",
                        "tool_calls": [
                            {
                                "id": verify_call_id,
                                "type": "function",
                                "function": {
                                    "name": "verify_user_action",
                                    "arguments": json.dumps(
                                        {
                                            "expected_transition": _as_plain(
                                                step.expected_transition
                                            ),
                                            "step_number": step_number,
                                        },
                                        separators=(",", ":"),
                                        sort_keys=True,
                                    ),
                                },
                            }
                        ],
                        "timestamp": timestamp_ms + len(messages) + 4,
                    },
                    {
                        "role": "tool",
                        "content": json.dumps(
                            {
                                "trusted_user_action": True,
                                "verification_passed": True,
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "tool_call_id": verify_call_id,
                        "timestamp": timestamp_ms + len(messages) + 5,
                    },
                    {
                        "role": "assistant",
                        "content": "Record the verified transition for deterministic replay.",
                        "tool_calls": [
                            {
                                "id": f"record-{step.step_id}",
                                "type": "function",
                                "function": {
                                    "name": "record_verified_replay_step",
                                    "arguments": json.dumps(
                                        {
                                            "instruction": step.instruction,
                                            "selectors": _as_plain(step.selectors),
                                            "step_id": str(step.step_id),
                                        },
                                        separators=(",", ":"),
                                        sort_keys=True,
                                    ),
                                },
                            }
                        ],
                        "timestamp": timestamp_ms + len(messages) + 6,
                    },
                    {
                        "role": "tool",
                        "content": json.dumps(
                            {
                                "expected_transition": _as_plain(step.expected_transition),
                                "recorded": True,
                                "replay_strategy": "selector-first",
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "tool_call_id": f"record-{step.step_id}",
                        "timestamp": timestamp_ms + len(messages) + 7,
                    },
                )
            )
        messages.append(
            {
                "role": "assistant",
                "content": (
                    "Verified WebAccessible task trajectory and canonical procedure:\n\n"
                    f"{markdown}\n\n"
                    "Verified terminal outcome:\n"
                    f"{json.dumps(episode_payload, separators=(',', ':'), sort_keys=True)}"
                ),
                "timestamp": timestamp_ms + len(messages),
            },
        )
        added = await self._provider.add(
            session_id,
            user_id,
            messages,
            mode="agent",
            async_mode=False,
        )
        flushed = await self._provider.flush(session_id)

        case_ids = _extract_provider_ids((added.data, flushed.data), "case")
        skill_ids = _extract_provider_ids((added.data, flushed.data), "skill")
        episode_ids = _extract_provider_ids((added.data, flushed.data), "episode")
        (
            retrieved_case_ids,
            retrieved_skill_ids,
            retrieved_episode_ids,
            replay_skill_id,
            retrieval_attempts,
        ) = await self._retrieve_saved_memory(
            user_id=user_id,
            session_id=session_id,
            skill=skill_document,
            known_case_ids=case_ids,
            known_skill_ids=skill_ids,
            known_episode_ids=episode_ids,
        )
        case_ids = _unique((*case_ids, *retrieved_case_ids))
        skill_ids = _unique((*skill_ids, *retrieved_skill_ids))
        episode_ids = _unique((*episode_ids, *retrieved_episode_ids))
        primary_skill_id = replay_skill_id or (skill_ids[0] if skill_ids else None)
        return {
            "agent_id": self._provider.agent_id_for(user_id),
            "session_id": session_id,
            "case_id": case_ids[0] if case_ids else None,
            "case_ids": list(case_ids),
            "skill_id": primary_skill_id,
            "skill_ids": list(skill_ids),
            "episode_id": episode_ids[0] if episode_ids else None,
            "episode_ids": list(episode_ids),
            "indexing_status": "ready" if replay_skill_id else "indexing",
            "retrieval_attempts": retrieval_attempts,
            "add": _operation_receipt(added.data, include_message_count=True),
            "flush": _operation_receipt(flushed.data),
        }

    async def _retrieve_saved_memory(
        self,
        *,
        user_id: str,
        session_id: str,
        skill: SkillDocument,
        known_case_ids: Sequence[str],
        known_skill_ids: Sequence[str],
        known_episode_ids: Sequence[str],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str | None, int]:
        case_ids = list(known_case_ids)
        skill_ids = list(known_skill_ids)
        episode_ids = list(known_episode_ids)
        replay_skill_id: str | None = None
        attempts = 0

        for delay_seconds in _MEMORY_RETRIEVAL_DELAYS_SECONDS:
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            attempts += 1
            try:
                case_result, skill_result, episode_result = await asyncio.gather(
                    self._provider.get_agent_memory(
                        user_id,
                        "agent_case",
                        page=1,
                        page_size=100,
                        filters={"session_id": session_id},
                    ),
                    self._provider.get_agent_memory(
                        user_id,
                        "agent_skill",
                        page=1,
                        page_size=100,
                    ),
                    self._provider.get_user_memory(
                        user_id,
                        "episode",
                        page=1,
                        page_size=100,
                        filters={"session_id": session_id},
                    ),
                )
            except EverOSProviderError as exc:
                if not exc.retryable:
                    break
                continue

            matching_cases = [
                item
                for item in _items(case_result.data, "agent_cases")
                if str(item.get("session_id") or "") == session_id
            ]
            case_ids.extend(_item_ids(matching_cases))

            matching_episodes = [
                item
                for item in _items(episode_result.data, "episodes")
                if str(item.get("session_id") or "") == session_id
            ]
            episode_ids.extend(_item_ids(matching_episodes))

            visible_skills = _items(skill_result.data, "agent_skills")
            case_ids.extend(_extract_provider_ids(visible_skills, "case"))
            replay_skill_id = _replay_skill_id(
                visible_skills,
                skill,
                known_skill_ids=skill_ids,
                known_case_ids=case_ids,
            )
            if replay_skill_id:
                skill_ids.append(replay_skill_id)

            case_ids = list(_unique(case_ids))
            skill_ids = list(_unique(skill_ids))
            episode_ids = list(_unique(episode_ids))
            if replay_skill_id and case_ids and episode_ids:
                break

        return (
            _unique(case_ids),
            _unique(skill_ids),
            _unique(episode_ids),
            replay_skill_id,
            attempts,
        )

    async def answer_episode(self, user_id: str, query: str) -> EpisodeAnswer:
        result = await self._provider.search(user_id, query, top_k=10)
        episodes = _items(result.user_memory, "episodes")
        if not episodes:
            return EpisodeAnswer(
                found=False,
                answer="No verified completion was found in memory.",
            )
        item = episodes[0]
        answer = str(item.get("episode") or item.get("summary") or "").strip()
        if not answer:
            return EpisodeAnswer(
                found=False,
                answer="No verified completion was found in memory.",
            )
        occurred_at = item.get("timestamp")
        return EpisodeAnswer(
            found=True,
            answer=answer,
            occurred_at=occurred_at,
            provider_episode_id=str(item.get("id")) if item.get("id") else None,
        )


def _normalize_setup_profile(data: Mapping[str, Any]) -> dict[str, str | bool | None]:
    supplied = dict(data)
    preferences = supplied.pop("preferences", None)
    unknown = set(supplied) - set(_SETUP_PROFILE_CATEGORIES)
    if unknown:
        raise ValueError(f"unsupported EverOS profile fields: {sorted(unknown)}")
    if preferences is not None:
        if not isinstance(preferences, Mapping):
            raise ValueError("preferences must be an object")
        unknown_preferences = set(preferences) - _PROFILE_PREFERENCE_FIELDS
        if unknown_preferences:
            raise ValueError(f"unsupported EverOS preference fields: {sorted(unknown_preferences)}")
        for field, value in preferences.items():
            supplied.setdefault(str(field), value)
    if not supplied:
        raise ValueError("profile data must include at least one reviewed setup field")

    normalized: dict[str, str | bool | None] = {}
    for field, value in supplied.items():
        if field == "voice_enabled":
            if not isinstance(value, bool):
                raise ValueError("voice_enabled must be a boolean")
            normalized[field] = value
            continue
        if field == "caregiver_mobile" and value is None:
            normalized[field] = None
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        text = value.strip()
        if field == "caregiver_mobile" and not text:
            normalized[field] = None
            continue
        if not text:
            raise ValueError(f"{field} must not be blank")
        if field == "participant_name" and len(text) > 80:
            raise ValueError("participant_name is too long")
        if field == "reading_size" and text not in {"standard", "large", "largest"}:
            raise ValueError("reading_size is not supported")
        if field == "timezone" and len(text) > 80:
            raise ValueError("timezone is too long")
        if field == "caregiver_mobile" and not 7 <= len(text) <= 32:
            raise ValueError("caregiver_mobile must contain between 7 and 32 characters")
        normalized[field] = text
    return normalized


def _profile_items_by_category(
    profiles: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    items: dict[str, list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            category = value.get("category")
            item_id = value.get("item_id") or value.get("id")
            if isinstance(category, str) and isinstance(item_id, str) and item_id not in seen_ids:
                if category in _SETUP_PROFILE_CATEGORIES.values():
                    seen_ids.add(item_id)
                    items.setdefault(category, []).append(dict(value))
            for nested in value.values():
                visit(nested)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for nested in value:
                visit(nested)

    for profile in profiles:
        visit(profile.get("profile_data"))
    return items


def _profile_edit_operations(
    values: Mapping[str, str | bool | None],
    existing: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    operations: list[dict[str, Any]] = []
    updated_fields: list[str] = []
    removed_fields: list[str] = []
    reason = "Reviewed WebAccessible participant setup update."

    for field, value in values.items():
        category = _SETUP_PROFILE_CATEGORIES[field]
        current = list(existing.get(category, ()))
        if value is None:
            for item in current:
                item_id = str(item.get("item_id") or item.get("id") or "")
                if item_id:
                    operations.append(
                        {
                            "action": "delete",
                            "type": "explicit_info",
                            "item_id": item_id,
                            "reason": reason,
                        }
                    )
            if current:
                removed_fields.append(field)
            continue

        metadata = {
            "classification": (
                "private_contact" if field == "caregiver_mobile" else "reviewed_preference"
            ),
            "allowed_use": (
                "caregiver_delivery_only" if field == "caregiver_mobile" else "guidance"
            ),
        }
        item_data = {
            "category": category,
            "description": _profile_description(value),
            "metadata": metadata,
        }
        if current:
            first_id = str(current[0].get("item_id") or current[0].get("id") or "")
            if first_id:
                operations.append(
                    {
                        "action": "update",
                        "type": "explicit_info",
                        "item_id": first_id,
                        "data": item_data,
                        "reason": reason,
                    }
                )
            for duplicate in current[1:]:
                duplicate_id = str(duplicate.get("item_id") or duplicate.get("id") or "")
                if duplicate_id:
                    operations.append(
                        {
                            "action": "delete",
                            "type": "explicit_info",
                            "item_id": duplicate_id,
                            "reason": reason,
                        }
                    )
        else:
            operations.append(
                {
                    "action": "add",
                    "type": "explicit_info",
                    "data": item_data,
                    "reason": reason,
                }
            )
        updated_fields.append(field)
    return operations, updated_fields, removed_fields


def _profile_description(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _without_private_contact(data: Mapping[str, Any]) -> dict[str, Any]:
    private_category = _SETUP_PROFILE_CATEGORIES["caregiver_mobile"]

    def visit(value: Any) -> Any:
        if isinstance(value, Mapping):
            if value.get("category") == private_category:
                return _PRIVATE_VALUE_REMOVED
            result: dict[str, Any] = {}
            for key, nested in value.items():
                cleaned = visit(nested)
                if cleaned is not _PRIVATE_VALUE_REMOVED:
                    result[str(key)] = cleaned
            return result
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            result_items: list[Any] = []
            for nested in value:
                cleaned = visit(nested)
                if cleaned is not _PRIVATE_VALUE_REMOVED:
                    result_items.append(cleaned)
            return result_items
        return value

    cleaned = visit(data)
    return cleaned if isinstance(cleaned, dict) else {}


def _extract_provider_ids(value: Any, kind: str) -> tuple[str, ...]:
    singular_keys = {f"{kind}_id", f"agent_{kind}_id", f"provider_{kind}_id"}
    plural_keys = {f"{kind}_ids", f"agent_{kind}_ids", f"provider_{kind}_ids"}
    container_keys = {kind, f"agent_{kind}", f"{kind}_memory"}
    container_keys.update({f"{name}s" for name in tuple(container_keys)})
    found: list[str] = []

    def add(candidate: Any) -> None:
        if isinstance(candidate, str):
            candidate = candidate.strip()
            if candidate:
                found.append(candidate)

    def visit(current: Any, *, in_kind_container: bool = False) -> None:
        if isinstance(current, Mapping):
            if in_kind_container:
                add(current.get("id"))
            for raw_key, nested in current.items():
                key = str(raw_key).casefold()
                if key in singular_keys or key.endswith(f"_{kind}_id"):
                    add(nested)
                elif (
                    (key in plural_keys or key.endswith(f"_{kind}_ids"))
                    and isinstance(nested, Sequence)
                    and not isinstance(nested, (str, bytes, bytearray))
                ):
                    for candidate in nested:
                        add(candidate)
                visit(nested, in_kind_container=key in container_keys)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for nested in current:
                visit(nested, in_kind_container=in_kind_container)

    visit(value)
    return _unique(found)


def _replay_skill_id(
    items: Sequence[Mapping[str, Any]],
    expected: SkillDocument,
    *,
    known_skill_ids: Sequence[str],
    known_case_ids: Sequence[str],
) -> str | None:
    known_skills = set(known_skill_ids)
    known_cases = set(known_case_ids)
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        try:
            document = _skill_document(item)
        except (KeyError, TypeError, ValueError, yaml.YAMLError):
            continue
        if item_id in known_skills:
            return item_id
        if document.skill_key == expected.skill_key and document.revision == expected.revision:
            return item_id
        if document.source_session_id == expected.source_session_id:
            return item_id
        if known_cases.intersection(document.provider_case_ids):
            return item_id
    return None


def _item_ids(items: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return _unique(str(item.get("id") or "") for item in items)


def _unique(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _first_text(values: Iterable[object]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _operation_receipt(
    data: Mapping[str, Any],
    *,
    include_message_count: bool = False,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {"status": str(data.get("status") or "accepted")}
    if include_message_count:
        count = _optional_int(data.get("message_count"))
        if count is not None:
            receipt["message_count"] = count
    return receipt


def _require_identifier(name: str, value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} must not be blank")
    if len(value) > 128:
        raise ValueError(f"{name} is too long")
    return value


def _items(data: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _routine_summaries(items: Sequence[Mapping[str, Any]]) -> list[RoutineSummary]:
    routines: list[RoutineSummary] = []
    for item in items:
        try:
            front_matter = _skill_front_matter(str(item.get("content") or ""))
            routines.append(
                RoutineSummary(
                    id=str(item["id"]),
                    skill_key=front_matter.get("skill_key"),
                    revision=int(front_matter.get("revision", 1)),
                    name=str(item.get("name") or front_matter["name"]),
                    description=str(item.get("description") or "") or None,
                    start_url=str(front_matter["start_url"]),
                    source="everos",
                )
            )
        except (KeyError, TypeError, ValueError, yaml.YAMLError):
            continue
    return routines


def _skill_document(item: Mapping[str, Any]) -> SkillDocument:
    front_matter = _skill_front_matter(str(item.get("content") or ""))
    front_matter["provider_skill_id"] = str(item["id"])
    front_matter["provider_case_ids"] = list(item.get("source_case_ids") or [])
    return SkillDocument.model_validate(front_matter)


def _skill_front_matter(content: str) -> dict[str, Any]:
    if not content.startswith("---\n"):
        raise ValueError("EverOS skill content has no YAML front matter")
    closing = content.find("\n---", 4)
    if closing < 0:
        raise ValueError("EverOS skill front matter is not terminated")
    parsed = yaml.safe_load(content[4:closing])
    if not isinstance(parsed, dict):
        raise ValueError("EverOS skill front matter is not an object")
    return parsed


def _render_skill_markdown(skill: SkillDocument) -> str:
    front_matter = skill.model_dump(mode="json", exclude={"provider_skill_id", "provider_case_ids"})
    yaml_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=False).strip()
    lines = ["---", yaml_text, "---", "", f"# {skill.name}", ""]
    for index, step in enumerate(skill.steps, start=1):
        lines.append(f"{index}. {step.instruction}")
    return "\n".join(lines).strip() + "\n"


def _as_plain_dict(value: Any) -> dict[str, Any]:
    plain = _as_plain(value)
    if isinstance(plain, dict):
        return plain
    return {"value": plain}


def _as_plain(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _as_plain(value.to_dict())
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=False, exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): _as_plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_as_plain(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _map_error(exc: Exception) -> EverOSProviderError:
    if isinstance(exc, EverOSProviderError):
        return exc
    if isinstance(exc, TimeoutError):
        return EverOSProviderError(
            EverOSErrorCode.TIMEOUT,
            "EverOS did not respond before the request timeout.",
            retryable=True,
        )
    if isinstance(exc, EverOSStorageError):
        return EverOSProviderError(
            EverOSErrorCode.WRITE_FAILED,
            "EverOS storage did not accept the upload.",
            retryable=exc.status >= 500,
            status_code=exc.status,
        )
    if isinstance(exc, EverOSAPIError):
        status = int(exc.status) if str(exc.status).isdigit() else None
        if status in {401, 403}:
            code = EverOSErrorCode.UNAUTHORIZED
            retryable = False
        elif status == 429:
            code = EverOSErrorCode.RATE_LIMITED
            retryable = True
        elif status is not None and status >= 500:
            code = EverOSErrorCode.UNREACHABLE
            retryable = True
        else:
            code = EverOSErrorCode.INVALID_RESPONSE
            retryable = False
        return EverOSProviderError(
            code,
            "EverOS could not complete the memory operation.",
            retryable=retryable,
            status_code=status,
        )
    if isinstance(exc, EverOSError):
        return EverOSProviderError(
            EverOSErrorCode.INVALID_RESPONSE,
            "EverOS could not complete the memory operation.",
            retryable=False,
        )
    if isinstance(exc, OSError):
        return EverOSProviderError(
            EverOSErrorCode.UNREACHABLE,
            "EverOS is unreachable.",
            retryable=True,
        )
    return EverOSProviderError(
        EverOSErrorCode.INVALID_RESPONSE,
        "EverOS could not complete the memory operation.",
        retryable=False,
    )
