#!/usr/bin/env python3
"""Non-mutating EverOS readiness check for WebAccessible operations.

    uv run ops/verify-everos-readiness.py [--session-id ID] [--json]

This check calls only the read paths of the EverOS SDK: ``get`` for agent-owned
and user-owned memory, and optionally ``search``. It never calls ``add``,
``flush``, ``edit``, ``delete``, or ``upload``, so it can be run safely against
the production memory space at any time, including mid-incident.

It reports identifiers and counts. It never prints memory content, caregiver
contact metadata, or the API key.

Ownership follows the application contract in
``backend/app/integrations/everos/client.py``: user memory is addressed by
``user_id`` and agent memory by the stable agent ID ``webaccessible:{user_id}``.
The default probe identity mirrors the ``/ready`` route so ops and the hosted
app observe the same scope.

Evidence model:
  unconfigured  EVEROS_API_KEY is absent, so no call was possible.
  configured    The key is present but the SDK could not be loaded, so no live
                call was attempted.
  degraded      Live calls were attempted and the provider is unauthorized,
                unreachable, slow past budget, or returned an unusable envelope.
                Also used when a session's Case is visible but its Skill is not,
                which is the observable signature of indexing lag.
  healthy       The agent-scope read succeeded.
  verified      Agent-scope read, user-scope read, and search all succeeded with
                a schema-valid envelope inside the latency budget.

`verified` scopes to the EverOS read path only. It does not prove the teach
write, flush, or post-indexing readback that a skill claim depends on.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from ops_status import (  # noqa: E402
    LocalSubstitutionError,
    OpsState,
    Report,
    fail_usage,
    load_env_file,
    reject_local_endpoint,
)

# The /ready route probes routines for this identity; ops mirrors it so both
# observe the same EverOS scope.
DEFAULT_PROBE_USER = "webaccessible-readiness"

# Read paths only. Listed here so the intent is auditable from the file itself.
ALLOWED_OPERATIONS = ("get", "search")
FORBIDDEN_OPERATIONS = ("add", "flush", "edit", "delete", "upload")

USER_MEMORY_PROBE = "episode"
AGENT_MEMORY_PROBES = ("agent_skill", "agent_case")

# Envelope keys the application relies on when parsing each memory type.
EXPECTED_ENVELOPE_KEYS = {
    "agent_skill": "agent_skills",
    "agent_case": "agent_cases",
    "episode": "episodes",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Non-mutating EverOS readiness check.",
        epilog="This check never writes to EverOS.",
    )
    parser.add_argument(
        "--user-id",
        default=os.environ.get("OPS_EVEROS_PROBE_USER", DEFAULT_PROBE_USER),
        help="Probe identity. Defaults to the identity used by the /ready route.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help=(
            "Optional WebAccessible session ID. When given, the check reports "
            "whether that session's Case and Episode are visible yet, which is "
            "how indexing lag is observed without writing anything."
        ),
    )
    parser.add_argument(
        "--skip-search",
        action="store_true",
        help="Skip the hybrid search probe. Caps the verdict at healthy.",
    )
    parser.add_argument(
        "--latency-budget-ms",
        type=int,
        default=int(os.environ.get("OPS_EVEROS_LATENCY_BUDGET_MS", "20000")),
        help="Per-call latency budget in milliseconds. Default 20000.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("OPS_ENV_FILE", ".env"),
        help="Ignored env file to read configuration from when a value is unset.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a redacted JSON report.")
    return parser.parse_args(argv)


def resolve_setting(name: str, env_file_values: dict[str, str]) -> str | None:
    value = os.environ.get(name) or env_file_values.get(name)
    return value.strip() if value and value.strip() else None


def envelope_items(payload: Any, key: str) -> list[dict[str, Any]] | None:
    """Return the list under `key`, or None if the envelope is unusable."""

    data = payload
    if hasattr(data, "to_dict"):
        data = data.to_dict()
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, dict)]


def item_ids(items: list[dict[str, Any]]) -> list[str]:
    ids = []
    for item in items:
        identifier = str(item.get("id") or "").strip()
        if identifier:
            ids.append(identifier)
    return ids


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = Report("everos-readiness", "everos", as_json=args.json)

    env_values = load_env_file(args.env_file) if args.env_file else {}
    api_key = resolve_setting("EVEROS_API_KEY", env_values)
    host = resolve_setting("EVEROS_HOST", env_values)
    app_id = resolve_setting("EVEROS_APP_ID", env_values) or "default"
    project_id = resolve_setting("EVEROS_PROJECT_ID", env_values) or "default"
    timeout_text = resolve_setting("EVEROS_TIMEOUT_SECONDS", env_values) or "60"
    try:
        timeout = float(timeout_text)
    except ValueError:
        return fail_usage("EVEROS_TIMEOUT_SECONDS is not a number.")

    agent_id = f"webaccessible:{args.user_id}"

    report.section("Target")
    report.field("probe_user_id", args.user_id)
    report.field("agent_id", agent_id)
    report.field("app_id", app_id)
    report.field("project_id", project_id)
    report.field("host", host or "provider default")
    report.field("timeout_seconds", timeout)
    report.field("allowed_operations", ",".join(ALLOWED_OPERATIONS))
    report.field("forbidden_operations", ",".join(FORBIDDEN_OPERATIONS))
    report.field("session_id_filter", args.session_id or "not requested")

    report.boundary(
        [
            "A successful read proves the configured memory scope answers. It does not "
            "prove the WebAccessible teach path: add, flush, and post-indexing readback "
            "of a Case, Skill, and Episode remain unproven by this check.",
            "No skill revision was validated against contracts/skill.schema.json here.",
            "Counts and IDs are reported; memory content is deliberately never printed.",
        ]
    )

    if not api_key:
        report.section("Configuration")
        report.finding("fail", "EVEROS_API_KEY is not set in the environment or env file.")
        return report.conclude(
            OpsState.UNCONFIGURED,
            "Set EVEROS_API_KEY, then re-run. No EverOS call was attempted.",
        )

    try:
        reject_local_endpoint("EVEROS_HOST", host)
    except LocalSubstitutionError as error:
        return fail_usage(str(error))

    try:
        from everos_cloud.client import EverOS, EverOSError
    except ImportError:
        report.section("Configuration")
        report.finding(
            "fail",
            "The everos-cloud SDK is not importable. Run this check with "
            "'uv run ops/verify-everos-readiness.py' from the repository root.",
        )
        report.field("sdk_available", False)
        return report.conclude(
            OpsState.CONFIGURED,
            "The API key is present but no live call was attempted.",
        )

    report.section("Live read probes")
    results: dict[str, dict[str, Any]] = {}

    def probe(
        label: str,
        memory_type: str,
        *,
        user_id: str | None = None,
        agent_scope: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> None:
        started = time.monotonic()
        try:
            with EverOS(
                api_key,
                host=host,
                app_id=app_id,
                project_id=project_id,
                timeout=timeout,
            ) as client:
                payload = client.get(
                    memory_type,
                    user_id=user_id,
                    agent_id=agent_scope,
                    page=1,
                    page_size=25,
                    filters=filters,
                )
        except (EverOSError, OSError, TimeoutError, ValueError) as error:
            elapsed = int((time.monotonic() - started) * 1000)
            status = getattr(error, "status", None)
            code = "unauthorized" if status in {401, 403} else type(error).__name__
            results[label] = {"ok": False, "latency_ms": elapsed, "code": code}
            report.field(f"{label}.latency_ms", elapsed)
            report.finding("fail", f"The {label} read failed ({code}).")
            return

        elapsed = int((time.monotonic() - started) * 1000)
        key = EXPECTED_ENVELOPE_KEYS[memory_type]
        items = envelope_items(payload, key)
        if items is None:
            results[label] = {"ok": False, "latency_ms": elapsed, "code": "invalid_response"}
            report.field(f"{label}.latency_ms", elapsed)
            report.finding(
                "fail",
                f"The {label} read returned an envelope without a usable {key!r} list.",
            )
            return

        ids = item_ids(items)
        results[label] = {
            "ok": True,
            "latency_ms": elapsed,
            "count": len(items),
            "ids": ids,
        }
        report.field(f"{label}.latency_ms", elapsed)
        report.field(f"{label}.count", len(items))
        if ids:
            report.field(f"{label}.ids", ",".join(ids[:5]))
        if elapsed > args.latency_budget_ms:
            report.finding(
                "warn",
                f"The {label} read took {elapsed} ms, over the {args.latency_budget_ms} ms budget.",
            )

    for memory_type in AGENT_MEMORY_PROBES:
        filters = {"session_id": args.session_id} if args.session_id else None
        probe(memory_type, memory_type, agent_scope=agent_id, filters=filters)

    probe(
        USER_MEMORY_PROBE,
        USER_MEMORY_PROBE,
        user_id=args.user_id,
        filters={"session_id": args.session_id} if args.session_id else None,
    )

    search_ok = False
    if args.skip_search:
        report.finding("info", "--skip-search was given; the hybrid search path was not probed.")
    else:
        started = time.monotonic()
        try:
            with EverOS(
                api_key,
                host=host,
                app_id=app_id,
                project_id=project_id,
                timeout=timeout,
            ) as client:
                client.search(
                    "webaccessible readiness probe",
                    agent_id=agent_id,
                    method="hybrid",
                    top_k=1,
                )
            elapsed = int((time.monotonic() - started) * 1000)
            search_ok = True
            report.field("search.latency_ms", elapsed)
            if elapsed > args.latency_budget_ms:
                report.finding(
                    "warn",
                    f"Search took {elapsed} ms, over the {args.latency_budget_ms} ms budget.",
                )
        except (EverOSError, OSError, TimeoutError, ValueError) as error:
            elapsed = int((time.monotonic() - started) * 1000)
            report.field("search.latency_ms", elapsed)
            report.finding("fail", f"The search probe failed ({type(error).__name__}).")

    # -- indexing signal ---------------------------------------------------

    indexing_in_flight = False
    if args.session_id:
        report.section("Indexing signal")
        case = results.get("agent_case", {})
        skill = results.get("agent_skill", {})
        episode = results.get("episode", {})
        report.field("session.agent_case_visible", bool(case.get("count")))
        report.field("session.agent_skill_visible", bool(skill.get("count")))
        report.field("session.episode_visible", bool(episode.get("count")))
        if case.get("count") and not skill.get("count"):
            indexing_in_flight = True
            report.finding(
                "warn",
                "A Case for this session is visible but no Skill is. This is the "
                "observable signature of EverOS indexing lag. See "
                "docs/operations/runbook-everos-indexing-delay.md.",
            )
        elif not case.get("count"):
            report.finding(
                "info",
                "No Case is visible for this session yet. Either the teach run has not "
                "flushed, or extraction has not started.",
            )

    # -- verdict -----------------------------------------------------------

    agent_ok = bool(results.get("agent_skill", {}).get("ok"))
    user_ok = bool(results.get(USER_MEMORY_PROBE, {}).get("ok"))
    over_budget = any(
        isinstance(result.get("latency_ms"), int)
        and result["latency_ms"] > args.latency_budget_ms
        for result in results.values()
    )

    if report.failures or indexing_in_flight:
        summary = (
            "EverOS answered but the session's Skill is not visible yet."
            if indexing_in_flight and not report.failures
            else f"{len(report.failures)} EverOS read probe(s) failed."
        )
        return report.conclude(OpsState.DEGRADED, summary)

    if not agent_ok:
        return report.conclude(
            OpsState.DEGRADED,
            "The agent-scope read did not succeed, so no memory scope is proven.",
        )

    if args.skip_search or not search_ok or not user_ok or over_budget:
        reason = (
            "search was skipped"
            if args.skip_search
            else "search failed"
            if not search_ok
            else "the user-scope read failed"
            if not user_ok
            else "a probe exceeded the latency budget"
        )
        return report.conclude(
            OpsState.HEALTHY,
            f"The EverOS agent-scope read succeeded, but {reason}, so the read path "
            "is not verified.",
        )

    return report.conclude(
        OpsState.VERIFIED,
        "Agent-scope, user-scope, and search reads all returned schema-valid envelopes "
        "within the latency budget.",
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
