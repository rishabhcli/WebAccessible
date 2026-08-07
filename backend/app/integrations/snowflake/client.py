"""Snowflake system-of-record and Cortex SQL integration."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any, Final

import snowflake.connector
from snowflake.connector import errors as snowflake_errors

from backend.app.config import Settings
from backend.app.contracts.models import ProviderReadiness, ProviderState

logger = logging.getLogger(__name__)


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


@dataclass(slots=True)
class PoolStats:
    """Observable pool counters used by readiness and tests."""

    opened: int = 0
    reused: int = 0
    discarded: int = 0
    idle: int = 0
    leased: int = 0


class SnowflakeConnectionPool:
    """A bounded, thread-safe pool of authenticated Snowflake connections.

    A Snowflake login costs roughly half a second to several seconds. Opening one per
    query put that cost on the guidance hot path twice per step and once per telemetry
    outbox row. Connections are therefore leased, returned, and reused until they go
    idle past ``max_idle_seconds`` or a call proves them unusable.
    """

    __slots__ = (
        "_acquire_timeout",
        "_closed",
        "_condition",
        "_factory",
        "_idle",
        "_leased",
        "_max_idle_seconds",
        "_max_size",
        "_stats",
    )

    def __init__(
        self,
        factory: Callable[[], Any],
        *,
        max_size: int = 4,
        max_idle_seconds: float = 240.0,
        acquire_timeout_seconds: float = 30.0,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        if max_idle_seconds <= 0:
            raise ValueError("max_idle_seconds must be positive")
        if acquire_timeout_seconds <= 0:
            raise ValueError("acquire_timeout_seconds must be positive")
        self._factory = factory
        self._max_size = max_size
        self._max_idle_seconds = max_idle_seconds
        self._acquire_timeout = acquire_timeout_seconds
        self._idle: list[tuple[Any, float]] = []
        self._leased = 0
        self._closed = False
        self._condition = threading.Condition(threading.Lock())
        self._stats = PoolStats()

    @property
    def stats(self) -> PoolStats:
        with self._condition:
            return PoolStats(
                opened=self._stats.opened,
                reused=self._stats.reused,
                discarded=self._stats.discarded,
                idle=len(self._idle),
                leased=self._leased,
            )

    def acquire(self) -> Any:
        """Lease a live connection, opening one only when the pool has spare capacity."""

        deadline = monotonic() + self._acquire_timeout
        while True:
            with self._condition:
                if self._closed:
                    raise SnowflakeProviderError(
                        SnowflakeErrorCode.UNREACHABLE,
                        "The Snowflake connection pool is closed.",
                        retryable=False,
                    )
                now = monotonic()
                while self._idle:
                    connection, released_at = self._idle.pop()
                    if now - released_at > self._max_idle_seconds or _is_closed(connection):
                        self._stats.discarded += 1
                        _close_quietly(connection)
                        continue
                    self._leased += 1
                    self._stats.reused += 1
                    return connection
                if self._leased < self._max_size:
                    self._leased += 1
                    break
                remaining = deadline - now
                if remaining <= 0 or not self._condition.wait(remaining):
                    raise SnowflakeProviderError(
                        SnowflakeErrorCode.TIMEOUT,
                        "No Snowflake connection became available before the timeout.",
                        retryable=True,
                    )

        try:
            connection = self._factory()
        except BaseException:
            with self._condition:
                self._leased -= 1
                self._condition.notify()
            raise
        with self._condition:
            self._stats.opened += 1
        return connection

    def release(self, connection: Any, *, reusable: bool) -> None:
        """Return a leased connection, discarding it when it can no longer be trusted."""

        with self._condition:
            self._leased -= 1
            if reusable and not self._closed and not _is_closed(connection):
                self._idle.append((connection, monotonic()))
                connection = None
            else:
                self._stats.discarded += 1
            self._condition.notify()
        if connection is not None:
            _close_quietly(connection)

    def close(self) -> None:
        """Close every idle connection and refuse new leases."""

        with self._condition:
            self._closed = True
            idle = [connection for connection, _ in self._idle]
            self._idle.clear()
            self._condition.notify_all()
        for connection in idle:
            _close_quietly(connection)


def _is_closed(connection: Any) -> bool:
    checker = getattr(connection, "is_closed", None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except Exception:
        return True


def _close_quietly(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        logger.debug("Discarding a Snowflake connection that could not be closed cleanly.")


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

    __slots__ = ("_pool", "_settings")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool = SnowflakeConnectionPool(
            lambda: snowflake.connector.connect(**self._connection_parameters()),
            max_size=settings.snowflake_max_connections,
            max_idle_seconds=settings.snowflake_connection_max_idle_seconds,
            acquire_timeout_seconds=float(settings.snowflake_login_timeout_seconds),
        )

    @property
    def pool_stats(self) -> PoolStats:
        return self._pool.stats

    async def close(self) -> None:
        """Release pooled Snowflake connections during shutdown."""

        await asyncio.to_thread(self._pool.close)

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

    async def count_and_complete(
        self,
        model: str,
        prompt: str,
        *,
        model_parameters: Mapping[str, Any],
        response_format: Mapping[str, Any],
    ) -> tuple[SnowflakeScalarResult, SnowflakeScalarResult]:
        """Measure input tokens and generate the completion in one round trip.

        The token estimate and the completion were previously two sequential statements,
        which doubled warehouse round trips on the guidance hot path. Snowflake evaluates
        both Cortex functions inside one statement, so the estimate stays a real
        ``AI_COUNT_TOKENS`` measurement of the exact prompt that was billed.
        """

        encoded_format = json.dumps(response_format, separators=(",", ":"))
        result = await self.query(
            """
            SELECT
              AI_COUNT_TOKENS(
                  'ai_complete', %s, %s, TO_OBJECT(PARSE_JSON(%s))
              ) AS input_tokens,
              AI_COMPLETE(
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
                encoded_format,
                model,
                prompt,
                json.dumps(model_parameters, separators=(",", ":")),
                encoded_format,
            ),
        )
        if not result.rows:
            raise SnowflakeProviderError(
                SnowflakeErrorCode.INVALID_RESPONSE,
                "Snowflake returned no Cortex result.",
                retryable=False,
                query_id=result.query_id,
            )
        row = result.rows[0]
        return (
            SnowflakeScalarResult(row.get("input_tokens"), result.query_id),
            SnowflakeScalarResult(row.get("completion"), result.query_id),
        )

    async def ai_complete_text(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> SnowflakeScalarResult:
        """Return plain Cortex text for narration paths that need no structured schema."""

        return await self.scalar(
            """
            SELECT AI_COMPLETE(
                model => %s,
                prompt => %s,
                model_parameters => TO_OBJECT(PARSE_JSON(%s))
            ) AS completion
            """,
            (
                model,
                prompt,
                json.dumps(
                    {"temperature": temperature, "max_tokens": max_tokens},
                    separators=(",", ":"),
                ),
            ),
        )

    async def ai_classify(
        self,
        text: str,
        categories: Sequence[str],
        *,
        task_description: str | None = None,
    ) -> SnowflakeScalarResult:
        """Classify untrusted page text into one supplied category with Cortex AI_CLASSIFY."""

        if not text.strip():
            raise ValueError("text must not be blank")
        labels = [label.strip() for label in categories if label.strip()]
        if len(labels) < 2:
            raise ValueError("at least two categories are required")
        config: dict[str, Any] = {"output_mode": "single"}
        if task_description:
            config["task_description"] = task_description
        return await self.scalar(
            """
            SELECT AI_CLASSIFY(
                %s,
                PARSE_JSON(%s),
                TO_OBJECT(PARSE_JSON(%s))
            ) AS classification
            """,
            (
                text,
                json.dumps(labels, separators=(",", ":")),
                json.dumps(config, separators=(",", ":")),
            ),
        )

    async def ai_embed(self, model: str, text: str) -> SnowflakeScalarResult:
        """Return a Cortex AI_EMBED vector used for routine phrasing similarity."""

        if not text.strip():
            raise ValueError("text must not be blank")
        return await self.scalar(
            "SELECT AI_EMBED(%s, %s) AS embedding",
            (model, text),
        )

    async def ai_embed_similarity(
        self,
        model: str,
        query: str,
        candidates: Sequence[str],
    ) -> list[tuple[str, float]]:
        """Rank candidate routine names against a spoken phrase inside Snowflake.

        Embedding and cosine similarity both run server-side in one statement so the
        vectors never cross the network, and the ranking stays reproducible for evidence.
        """

        if not query.strip():
            raise ValueError("query must not be blank")
        unique_candidates = list(dict.fromkeys(text for text in candidates if text.strip()))
        if not unique_candidates:
            return []
        result = await self.query(
            """
            WITH probe AS (
              SELECT AI_EMBED(%s, %s) AS vector
            ),
            candidate AS (
              SELECT value::string AS label, AI_EMBED(%s, value::string) AS vector
              FROM TABLE(FLATTEN(input => PARSE_JSON(%s)))
            )
            SELECT candidate.label AS label,
                   VECTOR_COSINE_SIMILARITY(candidate.vector, probe.vector) AS similarity
            FROM candidate, probe
            ORDER BY similarity DESC
            """,
            (
                model,
                query,
                model,
                json.dumps(unique_candidates, separators=(",", ":")),
            ),
        )
        ranked: list[tuple[str, float]] = []
        for row in result.rows:
            label = row.get("label")
            similarity = row.get("similarity")
            if isinstance(label, str) and similarity is not None:
                try:
                    ranked.append((label, float(similarity)))
                except (TypeError, ValueError):
                    continue
        return ranked

    def _execute_sync(
        self,
        sql: str,
        parameters: Sequence[Any] | Mapping[str, Any] | None,
        fetch: bool,
    ) -> SnowflakeQueryResult:
        connection = self._pool.acquire()
        cursor = None
        query_id: str | None = None
        reusable = True
        try:
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
            error = _map_error(exc, query_id=query_id)
            # A rejected statement leaves the session usable; a transport or auth failure
            # does not, so that connection must not go back into the pool.
            reusable = error.code is SnowflakeErrorCode.INVALID_RESPONSE
            raise error from exc
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    reusable = False
            self._pool.release(connection, reusable=reusable)

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
            # Pooled connections outlive a single statement, so the connector must
            # heartbeat the session instead of letting the auth token lapse.
            "client_session_keep_alive": True,
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
