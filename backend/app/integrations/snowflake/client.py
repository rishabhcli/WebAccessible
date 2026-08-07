"""Snowflake system-of-record and Cortex SQL integration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any, Final

import snowflake.connector
from snowflake.connector import errors as snowflake_errors

from backend.app.config import Settings
from backend.app.contracts.models import ProviderReadiness, ProviderState


class SnowflakeErrorCode(StrEnum):
    UNCONFIGURED = "unconfigured"
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    WRITE_FAILED = "write_failed"


class SnowflakeProviderError(RuntimeError):
    """A sanitized Snowflake failure suitable for readiness and sync state."""

    def __init__(
        self,
        code: SnowflakeErrorCode,
        message: str,
        *,
        retryable: bool,
        query_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.query_id = query_id


@dataclass(frozen=True, slots=True)
class SnowflakeQueryResult:
    rows: tuple[dict[str, Any], ...]
    query_id: str | None
    row_count: int


@dataclass(frozen=True, slots=True)
class SnowflakeScalarResult:
    value: Any
    query_id: str | None


@dataclass(frozen=True, slots=True)
class _TableSpec:
    table: str
    key: str
    columns: frozenset[str]
    variant_columns: frozenset[str] = frozenset()


_TABLE_SPECS: Final = {
    "session_step": _TableSpec(
        "SESSION_STEPS",
        "event_id",
        frozenset(
            {
                "session_id",
                "user_id",
                "step_no",
                "task_name",
                "skill_id",
                "url_domain",
                "action",
                "model_used",
                "input_tokens",
                "output_tokens",
                "credits",
                "replayed_from_memory",
                "latency_ms",
                "outcome",
                "ts",
                "event_id",
                "schema_version",
                "run_id",
                "task_id",
                "step_id",
                "guidance_mode",
                "sync_attempt",
                "source_environment",
                "browserbase_session_id",
                "page_id",
                "page_instance_id",
                "model_call_id",
                "selector_tier",
                "selector_result",
                "verification_predicate",
                "verification_result",
                "trusted_user_action",
                "terminal_provenance",
                "synchronized_at",
            }
        ),
    ),
    "session_run": _TableSpec(
        "SESSION_RUNS",
        "run_id",
        frozenset(
            {
                "run_id",
                "session_id",
                "user_id",
                "task_id",
                "task_name",
                "mode",
                "skill_id",
                "skill_revision",
                "terminal_outcome",
                "terminal_provenance",
                "verified_amount",
                "verified_currency",
                "source_environment",
                "fixture_mode",
                "build_commit",
                "browserbase_session_id",
                "everos_case_id",
                "everos_skill_id",
                "everos_episode_id",
                "sync_status",
                "started_at",
                "ended_at",
                "last_synced_at",
                "updated_at",
            }
        ),
    ),
    "browser_session": _TableSpec(
        "BROWSER_SESSIONS",
        "browserbase_session_id",
        frozenset(
            {
                "browserbase_session_id",
                "session_id",
                "run_id",
                "user_id",
                "region",
                "provider_status",
                "terminal_reason",
                "provider_limit_state",
                "agent_surface_used",
                "source_environment",
                "sync_status",
                "created_at",
                "cdp_attached_at",
                "live_view_ready_at",
                "first_trusted_user_action_at",
                "terminate_requested_at",
                "terminated_at",
                "last_provider_check_at",
                "last_synced_at",
                "updated_at",
            }
        ),
    ),
    "model_call": _TableSpec(
        "MODEL_CALLS",
        "call_id",
        frozenset(
            {
                "call_id",
                "session_id",
                "run_id",
                "user_id",
                "event_id",
                "step_id",
                "guidance_mode",
                "provider",
                "model",
                "model_version",
                "estimated_input_tokens",
                "actual_input_tokens",
                "actual_cached_input_tokens",
                "actual_reasoning_tokens",
                "actual_output_tokens",
                "usage_status",
                "latency_ms",
                "status",
                "provider_response_id_hash",
                "source_environment",
                "requested_at",
                "completed_at",
                "synchronized_at",
            }
        ),
    ),
    "model_cost": _TableSpec(
        "MODEL_COSTS",
        "cost_id",
        frozenset(
            {
                "cost_id",
                "call_id",
                "session_id",
                "run_id",
                "user_id",
                "rate_card_version",
                "actual_input_tokens",
                "actual_cached_input_tokens",
                "actual_reasoning_tokens",
                "actual_output_tokens",
                "input_amount",
                "cached_input_amount",
                "reasoning_amount",
                "output_amount",
                "credits",
                "amount_currency",
                "currency",
                "amount_usd",
                "calculation_status",
                "source_environment",
                "calculated_at",
            }
        ),
    ),
    "rate_card": _TableSpec(
        "COST_RATE_CARDS",
        "rate_card_id",
        frozenset(
            {
                "rate_card_id",
                "rate_card_version",
                "provider",
                "model",
                "model_version",
                "token_class",
                "unit_quantity",
                "unit_price",
                "currency",
                "usd_conversion_rate",
                "source_reference",
                "rounding_rule",
                "effective_from",
                "effective_to",
            }
        ),
    ),
    "telemetry_ingestion": _TableSpec(
        "TELEMETRY_INGESTION",
        "event_id",
        frozenset(
            {
                "event_id",
                "session_id",
                "run_id",
                "user_id",
                "target_table",
                "payload_hash",
                "source_environment",
                "status",
                "attempt_count",
                "first_attempt_at",
                "last_attempt_at",
                "synchronized_at",
                "last_error_code",
                "updated_at",
            }
        ),
    ),
    "escalation": _TableSpec(
        "ESCALATIONS",
        "escalation_id",
        frozenset(
            {
                "escalation_id",
                "session_id",
                "run_id",
                "user_id",
                "reason",
                "status",
                "delivery_channel",
                "delivery_attempt_count",
                "delivery_attempted_at",
                "delivery_receipt_at",
                "provider_message_id_hash",
                "caregiver_response_status",
                "caregiver_response_metadata",
                "caregiver_response_at",
                "source_environment",
                "updated_at",
            }
        ),
        frozenset({"caregiver_response_metadata"}),
    ),
    "skill_revision": _TableSpec(
        "SKILL_REVISION_LINKS",
        "skill_revision_link_id",
        frozenset(
            {
                "skill_revision_link_id",
                "skill_key",
                "revision",
                "everos_skill_id",
                "everos_case_id",
                "source_session_id",
                "source_run_id",
                "source_step_id",
                "parent_revision",
                "task_outcome",
                "repair_reason",
                "provider_status",
                "indexing_status",
                "is_current",
                "source_environment",
                "written_at",
                "retrieved_at",
            }
        ),
    ),
    "selector_attempt": _TableSpec(
        "SELECTOR_ATTEMPTS",
        "selector_attempt_id",
        frozenset(
            {
                "selector_attempt_id",
                "event_id",
                "session_id",
                "run_id",
                "user_id",
                "step_id",
                "attempt_no",
                "selector_tier",
                "selector_fingerprint",
                "resolution_result",
                "matched_candidate_count",
                "verification_predicate",
                "verification_result",
                "trusted_user_action",
                "replayed_from_memory",
                "model_call_id",
                "source_environment",
                "observed_at",
            }
        ),
    ),
}

_KIND_ALIASES: Final = {
    "step": "session_step",
    "run": "session_run",
    "browser": "browser_session",
    "cost": "model_cost",
    "rate": "rate_card",
    "ingestion": "telemetry_ingestion",
    "skill": "skill_revision",
    "selector": "selector_attempt",
}


class SnowflakeAdapter:
    """Live Snowflake query, outbox sync, cost view, and Cortex primitive adapter."""

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def readiness(self) -> ProviderReadiness:
        if not self._settings.snowflake_configured:
            return ProviderReadiness(
                state=ProviderState.UNCONFIGURED,
                configured=False,
                detail="Snowflake environment variables are not fully configured.",
            )
        started = monotonic()
        try:
            await self.scalar("SELECT 1")
        except SnowflakeProviderError as exc:
            return ProviderReadiness(
                state=ProviderState.UNAVAILABLE,
                configured=True,
                reachable=exc.code is not SnowflakeErrorCode.UNREACHABLE,
                authorized=False,
                last_checked_at=datetime.now(UTC),
                latency_ms=int((monotonic() - started) * 1000),
                error_code=exc.code.value,
                detail=str(exc),
            )
        return ProviderReadiness(
            state=ProviderState.AUTHORIZED,
            configured=True,
            reachable=True,
            authorized=True,
            last_checked_at=datetime.now(UTC),
            latency_ms=int((monotonic() - started) * 1000),
            detail="Snowflake service connection is authorized.",
        )

    async def sync_outbox(self, kind: str, payload: Mapping[str, Any]) -> bool:
        canonical_kind = _KIND_ALIASES.get(kind, kind)
        spec = _TABLE_SPECS.get(canonical_kind)
        if spec is None:
            raise ValueError(f"unsupported Snowflake outbox kind: {kind!r}")
        normalized_payload = self._normalize_outbox_payload(canonical_kind, payload, spec)
        unknown = set(normalized_payload) - spec.columns
        if unknown:
            raise ValueError(f"unsupported fields for {canonical_kind}: {sorted(unknown)}")
        if spec.key not in normalized_payload or normalized_payload[spec.key] in {None, ""}:
            raise ValueError(f"outbox payload requires stable key {spec.key!r}")

        columns = [spec.key, *sorted(set(normalized_payload) - {spec.key})]
        source_values: list[str] = []
        parameters: list[Any] = []
        for column in columns:
            value = normalized_payload[column]
            if column in spec.variant_columns:
                source_values.append(f"TO_VARIANT(PARSE_JSON(%s)) AS {column}")
                parameters.append(json.dumps(value, separators=(",", ":"), default=str))
            else:
                source_values.append(f"%s AS {column}")
                parameters.append(_bind_value(value))
        updates = [column for column in columns if column != spec.key]
        if not updates:
            updates = [spec.key]
        matched_clause = ""
        if canonical_kind != "rate_card":
            matched_clause = f"""
            WHEN MATCHED THEN UPDATE SET
              {", ".join(f"target.{column} = source.{column}" for column in updates)}
            """
        sql = f"""
            MERGE INTO {spec.table} AS target
            USING (SELECT {", ".join(source_values)}) AS source
              ON target.{spec.key} = source.{spec.key}
            {matched_clause}
            WHEN NOT MATCHED THEN INSERT ({", ".join(columns)})
              VALUES ({", ".join(f"source.{column}" for column in columns)})
        """
        try:
            await self.execute(sql, parameters)
        except SnowflakeProviderError as exc:
            if exc.code not in {SnowflakeErrorCode.UNAUTHORIZED, SnowflakeErrorCode.RATE_LIMITED}:
                raise SnowflakeProviderError(
                    SnowflakeErrorCode.WRITE_FAILED,
                    "Snowflake did not synchronize the outbox item.",
                    retryable=exc.retryable,
                    query_id=exc.query_id,
                ) from exc
            raise
        return True

    def _normalize_outbox_payload(
        self,
        kind: str,
        payload: Mapping[str, Any],
        spec: _TableSpec,
    ) -> dict[str, Any]:
        normalized = dict(payload)
        if kind == "model_call":
            if "actual_input_tokens" not in normalized and "input_tokens" in normalized:
                normalized["actual_input_tokens"] = normalized["input_tokens"]
            if "actual_output_tokens" not in normalized and "output_tokens" in normalized:
                normalized["actual_output_tokens"] = normalized["output_tokens"]
            normalized.pop("input_tokens", None)
            normalized.pop("output_tokens", None)

            has_actual_usage = all(
                normalized.get(field) is not None
                for field in ("actual_input_tokens", "actual_output_tokens")
            )
            normalized.setdefault("usage_status", "actual" if has_actual_usage else "unavailable")

            # These fields belong to MODEL_COSTS and are retained in the local ledger
            # until a complete, independently keyed model-cost row is available.
            normalized.pop("rate_card_version", None)
            normalized.pop("cost_usd", None)

        if "source_environment" in spec.columns:
            normalized.setdefault("source_environment", self._settings.app_env.value)
        return normalized

    async def cost_runs(self, user_id: str) -> list[dict[str, Any]]:
        if not user_id.strip():
            raise ValueError("user_id must not be blank")
        result = await self.query(
            """
            SELECT user_id, task_id, task_name, run_no, run_id, run_kind,
                   started_at, terminal_outcome, skill_id, skill_revision,
                   model_call_count, actual_model_tokens, cost_status,
                   actual_cost_usd, cold_baseline_usd, cost_reduction_ratio
            FROM V_COLD_WARM_COST_CURVE
            WHERE user_id = %s
            ORDER BY task_id, run_no
            """,
            (user_id,),
        )
        return list(result.rows)

    async def query(
        self,
        sql: str,
        parameters: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> SnowflakeQueryResult:
        return await asyncio.to_thread(self._execute_sync, sql, parameters, True)

    async def execute(
        self,
        sql: str,
        parameters: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> SnowflakeQueryResult:
        return await asyncio.to_thread(self._execute_sync, sql, parameters, False)

    async def scalar(
        self,
        sql: str,
        parameters: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> SnowflakeScalarResult:
        result = await self.query(sql, parameters)
        if not result.rows:
            raise SnowflakeProviderError(
                SnowflakeErrorCode.INVALID_RESPONSE,
                "Snowflake returned no result.",
                retryable=False,
                query_id=result.query_id,
            )
        first_row = result.rows[0]
        return SnowflakeScalarResult(next(iter(first_row.values())), result.query_id)

    async def count_ai_complete_tokens(
        self,
        model: str,
        prompt: str,
        response_format: Mapping[str, Any],
    ) -> SnowflakeScalarResult:
        return await self.scalar(
            """
            SELECT AI_COUNT_TOKENS(
                'ai_complete', %s, %s, TO_OBJECT(PARSE_JSON(%s))
            ) AS input_tokens
            """,
            (model, prompt, json.dumps(response_format, separators=(",", ":"))),
        )

    async def ai_complete(
        self,
        model: str,
        prompt: str,
        *,
        model_parameters: Mapping[str, Any],
        response_format: Mapping[str, Any],
    ) -> SnowflakeScalarResult:
        return await self.scalar(
            """
            SELECT AI_COMPLETE(
                model => %s,
                prompt => %s,
                model_parameters => TO_OBJECT(PARSE_JSON(%s)),
                response_format => TO_OBJECT(PARSE_JSON(%s)),
                show_details => TRUE
            ) AS completion
            """,
            (
                model,
                prompt,
                json.dumps(model_parameters, separators=(",", ":")),
                json.dumps(response_format, separators=(",", ":")),
            ),
        )

    def _execute_sync(
        self,
        sql: str,
        parameters: Sequence[Any] | Mapping[str, Any] | None,
        fetch: bool,
    ) -> SnowflakeQueryResult:
        connection = None
        cursor = None
        query_id: str | None = None
        try:
            connection = snowflake.connector.connect(**self._connection_parameters())
            cursor = connection.cursor()
            execute_parameters = dict(parameters) if isinstance(parameters, Mapping) else parameters
            cursor.execute(sql, execute_parameters)
            query_id = getattr(cursor, "sfqid", None)
            rows: list[dict[str, Any]] = []
            if fetch and cursor.description:
                names = [_column_name(column).lower() for column in cursor.description]
                rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
            else:
                connection.commit()
            affected_rows = cursor.rowcount if cursor.rowcount is not None else 0
            return SnowflakeQueryResult(
                rows=tuple(rows),
                query_id=query_id,
                row_count=len(rows) if fetch else max(affected_rows, 0),
            )
        except Exception as exc:
            raise _map_error(exc, query_id=query_id) from exc
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    def _connection_parameters(self) -> dict[str, Any]:
        settings = self._settings
        if not settings.snowflake_configured or settings.snowflake_password is None:
            raise SnowflakeProviderError(
                SnowflakeErrorCode.UNCONFIGURED,
                "Snowflake is not configured.",
                retryable=False,
            )
        return {
            "account": settings.snowflake_account,
            "user": settings.snowflake_user,
            "password": settings.snowflake_password.get_secret_value(),
            "role": settings.snowflake_role,
            "warehouse": settings.snowflake_warehouse,
            "database": settings.snowflake_database,
            "schema": settings.snowflake_schema,
            "application": "WEBACCESSIBLE",
            "login_timeout": settings.snowflake_login_timeout_seconds,
            "network_timeout": settings.snowflake_network_timeout_seconds,
            "client_session_keep_alive": False,
            "session_parameters": {"QUERY_TAG": "webaccessible"},
        }


def _column_name(column: Any) -> str:
    name = getattr(column, "name", None)
    return str(name if name is not None else column[0])


def _bind_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"), separators=(",", ":"))
    if isinstance(value, StrEnum):
        return value.value
    return value


def _map_error(exc: Exception, *, query_id: str | None) -> SnowflakeProviderError:
    if isinstance(exc, SnowflakeProviderError):
        return exc
    if isinstance(exc, snowflake_errors.ProgrammingError):
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate == "28000":
            code = SnowflakeErrorCode.UNAUTHORIZED
            message = "Snowflake rejected the configured service credentials."
        else:
            code = SnowflakeErrorCode.INVALID_RESPONSE
            message = "Snowflake rejected the requested operation."
        return SnowflakeProviderError(code, message, retryable=False, query_id=query_id)
    if isinstance(exc, snowflake_errors.OperationalError | snowflake_errors.InterfaceError):
        return SnowflakeProviderError(
            SnowflakeErrorCode.UNREACHABLE,
            "Snowflake is unreachable.",
            retryable=True,
            query_id=query_id,
        )
    if isinstance(exc, TimeoutError):
        return SnowflakeProviderError(
            SnowflakeErrorCode.TIMEOUT,
            "Snowflake did not respond before the request timeout.",
            retryable=True,
            query_id=query_id,
        )
    if isinstance(exc, snowflake_errors.DatabaseError):
        return SnowflakeProviderError(
            SnowflakeErrorCode.UNREACHABLE,
            "Snowflake could not complete the operation.",
            retryable=True,
            query_id=query_id,
        )
    return SnowflakeProviderError(
        SnowflakeErrorCode.INVALID_RESPONSE,
        "Snowflake could not complete the operation.",
        retryable=False,
        query_id=query_id,
    )
