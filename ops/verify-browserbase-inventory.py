#!/usr/bin/env python3
"""Browserbase account and active-session inventory. Creates nothing.

    uv run ops/verify-browserbase-inventory.py [--json]

This check lists projects, reads project usage, and lists sessions by status. It
never creates a session, never requests Live View or devtools URLs, and never
reads a session `connect_url`, so no CDP capability can leak through its output.
Termination is also out of scope: reclaiming a specific orphaned session is an
operator action documented in docs/operations/runbook-browserbase-exhaustion.md.

WebAccessible-owned sessions are identified by the `webaccessibleSessionId` key
the browser adapter writes into Browserbase user metadata. Sessions in the same
account that lack that key belong to something else and are reported separately
rather than being treated as WebAccessible evidence.

Evidence model:
  unconfigured  BROWSERBASE_API_KEY is absent, so no call was possible.
  configured    The key is present but the SDK could not be loaded, so no live
                call was attempted.
  degraded      Live calls were attempted and the provider is unauthorized or
                unreachable, or concurrency headroom is exhausted, or a
                WebAccessible-owned session has outlived the configured session
                timeout and is billing as an orphan.
  healthy       Projects and sessions were listed and headroom remains.
  verified      healthy PLUS project usage was readable and no WebAccessible-
                owned orphan is present.

`verified` scopes to account and session inventory. It does not prove the
WebAccessible session lifecycle: create, Live View, CDP attach, trusted
participant input, and provider-confirmed termination remain unproven here.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from ops_status import (  # noqa: E402
    LocalSubstitutionError,
    OpsState,
    Report,
    fail_usage,
    load_env_file,
    reject_local_endpoint,
)

SessionStatus = Literal["PENDING", "RUNNING", "ERROR", "TIMED_OUT", "COMPLETED"]

# Statuses that consume a concurrency slot right now.
ACTIVE_STATUSES: tuple[SessionStatus, ...] = ("RUNNING", "PENDING")
# Statuses that are finished, listed only for recent-failure context.
TERMINAL_STATUSES: tuple[SessionStatus, ...] = ("ERROR", "TIMED_OUT", "COMPLETED")

# Metadata keys the WebAccessible browser adapter writes on create.
OWNERSHIP_KEY = "webaccessibleSessionId"
AGENT_SURFACE_KEY = "agentSurfaceUsed"

# Session fields this check is allowed to read. `connect_url` is deliberately
# absent: it is a CDP capability, not inventory.
REPORTED_SESSION_FIELDS = (
    "id",
    "status",
    "region",
    "keep_alive",
    "created_at",
    "started_at",
    "expires_at",
    "ended_at",
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Browserbase account and active-session inventory. Creates nothing.",
        epilog="This check never creates, attaches to, or terminates a session.",
    )
    parser.add_argument(
        "--session-timeout-seconds",
        type=int,
        default=int(os.environ.get("BROWSERBASE_SESSION_TIMEOUT_SECONDS", "900")),
        help=(
            "Configured managed-session timeout. An owned session older than this "
            "is reported as an orphan. Default 900, matching the app default."
        ),
    )
    parser.add_argument(
        "--skip-usage",
        action="store_true",
        help="Skip the project usage read. Caps the verdict at healthy.",
    )
    parser.add_argument(
        "--include-recent-terminal",
        action="store_true",
        help="Also count recently ended sessions for failure context.",
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


def as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "to_dict"):
        dumped = value.to_dict()
        return dumped if isinstance(dumped, dict) else {}
    return value if isinstance(value, dict) else {}


def session_age_seconds(session: Any, now: datetime) -> int | None:
    started = getattr(session, "started_at", None) or getattr(session, "created_at", None)
    if not isinstance(started, datetime):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return int((now - started).total_seconds())


def owned_session_id(session: Any) -> str | None:
    metadata = getattr(session, "user_metadata", None)
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(OWNERSHIP_KEY)
    return str(value) if value else None


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = Report("browserbase-inventory", "browserbase", as_json=args.json)

    env_values = load_env_file(args.env_file) if args.env_file else {}
    api_key = resolve_setting("BROWSERBASE_API_KEY", env_values)
    base_url = resolve_setting("BROWSERBASE_BASE_URL", env_values)
    region = resolve_setting("BROWSERBASE_REGION", env_values) or "us-west-2"

    report.section("Target")
    report.field("configured_region", region)
    report.field("session_timeout_seconds", args.session_timeout_seconds)
    report.field("creates_sessions", False)
    report.field("reads_live_view_or_cdp", False)
    report.field("api_base_url_override", "set" if base_url else "provider default")

    report.boundary(
        [
            "Listing sessions proves account access. It does not prove the WebAccessible "
            "lifecycle: create, Live View, CDP attach, trusted participant input, and "
            "provider-confirmed termination remain unproven by this check.",
            "Sessions in this account that carry no webaccessibleSessionId metadata are "
            "not WebAccessible evidence, even when they completed successfully.",
            "Concurrency headroom is a point-in-time reading. It does not reserve a slot "
            "for a session you are about to start.",
            "No Live View or CDP URL was requested, so this output cannot be used to "
            "attach to any session.",
        ]
    )

    if not api_key:
        report.section("Configuration")
        report.finding("fail", "BROWSERBASE_API_KEY is not set in the environment or env file.")
        return report.conclude(
            OpsState.UNCONFIGURED,
            "Set BROWSERBASE_API_KEY, then re-run. No Browserbase call was attempted.",
        )

    if base_url:
        try:
            reject_local_endpoint("BROWSERBASE_BASE_URL", base_url)
        except LocalSubstitutionError as error:
            return fail_usage(str(error))
        if "browserbase.com" not in base_url:
            return fail_usage(
                "BROWSERBASE_BASE_URL points away from Browserbase. This check never "
                "accepts a stand-in for the cloud provider."
            )

    try:
        import browserbase
        from browserbase import Browserbase
    except ImportError:
        report.section("Configuration")
        report.finding(
            "fail",
            "The browserbase SDK is not importable. Run this check with "
            "'uv run ops/verify-browserbase-inventory.py' from the repository root.",
        )
        report.field("sdk_available", False)
        return report.conclude(
            OpsState.CONFIGURED,
            "The API key is present but no live call was attempted.",
        )

    client = Browserbase(api_key=api_key, timeout=30.0, max_retries=2)
    # BrowserbaseError is the SDK root; APIError and every transport, auth, and
    # status error descend from it.
    provider_errors = (browserbase.BrowserbaseError, OSError)

    # -- account inventory -------------------------------------------------

    report.section("Account inventory")
    try:
        projects = list(client.projects.list())
    except provider_errors as error:
        code = (
            "unauthorized"
            if isinstance(
                error, (browserbase.AuthenticationError, browserbase.PermissionDeniedError)
            )
            else type(error).__name__
        )
        report.finding("fail", f"The project list could not be read ({code}).")
        return report.conclude(
            OpsState.DEGRADED,
            "Browserbase is configured but the account could not be inventoried.",
        )

    report.field("project_count", len(projects))
    total_concurrency = 0
    project_ids: list[str] = []
    for project in projects:
        data = as_dict(project)
        project_id = str(data.get("id") or "")
        concurrency = int(data.get("concurrency") or 0)
        total_concurrency += concurrency
        project_ids.append(project_id)
        report.field(
            f"project.{project_id}",
            f"name={data.get('name')},concurrency={concurrency},"
            f"default_timeout={data.get('default_timeout')}",
        )
    report.field("total_concurrency_limit", total_concurrency)
    if total_concurrency == 0:
        report.finding(
            "warn", "No project reports a concurrency limit, so headroom cannot be computed."
        )

    # -- usage -------------------------------------------------------------

    usage_ok = False
    if args.skip_usage:
        report.finding("info", "--skip-usage was given; project usage was not read.")
    else:
        report.section("Project usage")
        usage_failures = 0
        for project_id in project_ids:
            if not project_id:
                continue
            try:
                usage = as_dict(client.projects.usage(project_id))
            except provider_errors as error:
                usage_failures += 1
                report.finding(
                    "warn",
                    f"Usage for project {project_id} could not be read "
                    f"({type(error).__name__}).",
                )
                continue
            report.field(
                f"usage.{project_id}",
                f"browser_minutes={usage.get('browser_minutes')},"
                f"proxy_bytes={usage.get('proxy_bytes')}",
            )
        usage_ok = bool(project_ids) and usage_failures == 0

    # -- active session inventory -----------------------------------------

    report.section("Active session inventory")
    now = datetime.now(UTC)
    active_sessions: list[Any] = []
    for status in ACTIVE_STATUSES:
        try:
            found = list(client.sessions.list(status=status))
        except provider_errors as error:
            report.finding(
                "fail",
                f"Sessions with status {status} could not be listed ({type(error).__name__}).",
            )
            return report.conclude(
                OpsState.DEGRADED,
                "The account answered but the active-session inventory is incomplete.",
            )
        report.field(f"sessions.{status.lower()}", len(found))
        active_sessions.extend(found)

    owned_active: list[tuple[str, Any, int | None]] = []
    foreign_active = 0
    agent_surface_sessions: list[str] = []
    for session in active_sessions:
        session_id = str(getattr(session, "id", "") or "")
        owner = owned_session_id(session)
        age = session_age_seconds(session, now)
        metadata = getattr(session, "user_metadata", None)
        if isinstance(metadata, dict) and metadata.get(AGENT_SURFACE_KEY) is True:
            agent_surface_sessions.append(session_id)
        if owner:
            owned_active.append((session_id, session, age))
        else:
            foreign_active += 1

    report.field("active_sessions_total", len(active_sessions))
    report.field("active_sessions_webaccessible_owned", len(owned_active))
    report.field("active_sessions_other_owner", foreign_active)

    orphans: list[str] = []
    for session_id, session, age in owned_active:
        data = as_dict(session)
        summary = ",".join(
            f"{field}={data.get(field)}"
            for field in REPORTED_SESSION_FIELDS
            if field != "id" and data.get(field) is not None
        )
        report.field(f"owned_session.{session_id}", f"age_seconds={age},{summary}")
        if age is not None and age > args.session_timeout_seconds:
            orphans.append(session_id)

    if orphans:
        report.finding(
            "fail",
            f"{len(orphans)} WebAccessible-owned session(s) have outlived the "
            f"{args.session_timeout_seconds}s timeout and are still billing: "
            f"{', '.join(orphans)}. See docs/operations/runbook-browserbase-exhaustion.md.",
        )

    if agent_surface_sessions:
        report.finding(
            "fail",
            "A session reports agentSurfaceUsed=true. The product prohibits autonomous "
            f"Browserbase Agent actions: {', '.join(agent_surface_sessions)}.",
        )

    headroom = total_concurrency - len(active_sessions) if total_concurrency else None
    report.field("concurrency_headroom", headroom if headroom is not None else "unknown")
    if headroom is not None and headroom <= 0:
        report.finding(
            "fail",
            "No concurrency headroom remains. A new managed session will be refused. "
            "See docs/operations/runbook-browserbase-exhaustion.md.",
        )
    elif headroom is not None and headroom == 1:
        report.finding("warn", "Only one concurrency slot remains.")

    if args.include_recent_terminal:
        report.section("Recent terminal sessions")
        for status in TERMINAL_STATUSES:
            try:
                found = list(client.sessions.list(status=status))
            except provider_errors as error:
                report.finding(
                    "warn",
                    f"Sessions with status {status} could not be listed "
                    f"({type(error).__name__}).",
                )
                continue
            owned = sum(1 for session in found if owned_session_id(session))
            report.field(f"terminal.{status.lower()}", f"total={len(found)},owned={owned}")

    # -- verdict -----------------------------------------------------------

    if report.failures:
        return report.conclude(
            OpsState.DEGRADED,
            f"{len(report.failures)} inventory failure(s) that block a new managed session "
            "or violate the product's Browserbase constraints.",
        )

    if args.skip_usage or not usage_ok:
        return report.conclude(
            OpsState.HEALTHY,
            "Projects and active sessions were inventoried, but project usage was not "
            "read, so the account is not verified.",
        )

    return report.conclude(
        OpsState.VERIFIED,
        f"The account inventory is complete, {len(owned_active)} WebAccessible-owned "
        f"session(s) are active, no orphan is billing, and headroom remains.",
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
