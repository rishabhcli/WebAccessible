#!/usr/bin/env python3
"""Reconcile WebAccessible-owned Browserbase sessions against operational state.

Dry run is the default: the script reports what it would release and changes
nothing. Pass --execute to actually terminate the sessions it judged orphaned.

Reports are written to stdout as JSON (one object per cycle). Diagnostics go to
stderr. No API key, CDP URL, Live View URL, cookie, or page content is ever read
into a report, and a final sanitizer redacts anything that resembles one.

Exit codes:
  0  reconciliation completed with no failed termination
  1  reconciliation completed but at least one termination failed
  2  usage or configuration error (bad arguments, missing operational database)
  3  Browserbase was unreachable, unauthorized, or unconfigured
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import Settings, get_settings  # noqa: E402
from backend.app.integrations.browserbase.client import (  # noqa: E402
    BrowserbaseProviderError,
)
from backend.app.services.browser_reconciliation import (  # noqa: E402
    LocalStateUnavailableError,
    ReconciliationReport,
    SqliteLocalSessionStore,
    policy_from_settings,
)
from backend.app.workers.browser_reconciliation_worker import (  # noqa: E402
    BrowserReconciliationWorker,
    WorkerSchedule,
    build_reconciliation_worker,
)

EXIT_OK = 0
EXIT_FAILED_TERMINATION = 1
EXIT_USAGE = 2
EXIT_PROVIDER_UNAVAILABLE = 3

#: Cycle bound applied when an interval is requested without an explicit bound.
DEFAULT_LOOP_CYCLES = 12


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconcile-browserbase",
        description=(
            "Compare WebAccessible-owned Browserbase sessions with the operational "
            "SQLite store and release only the orphaned or expired ones."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually terminate orphaned sessions. Without this the run is a dry run.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Operational SQLite database path (defaults to OPERATIONAL_DATABASE_PATH).",
    )
    parser.add_argument(
        "--environment",
        default=None,
        help="Owner metadata environment to reconcile (defaults to APP_ENV).",
    )
    parser.add_argument(
        "--any-environment",
        action="store_true",
        help="Inspect owned sessions from every environment. Dry run only.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Run periodically instead of once. Requires a cycle or runtime bound.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help=(
            "Maximum number of cycles. Defaults to 1 without --interval and to "
            f"{DEFAULT_LOOP_CYCLES} with --interval when no runtime bound is given."
        ),
    )
    parser.add_argument(
        "--max-runtime",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Wall-clock bound for a periodic run.",
    )
    parser.add_argument(
        "--lease-ttl",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Longest a session may be held (defaults to BROWSERBASE_SESSION_TIMEOUT_SECONDS).",
    )
    parser.add_argument(
        "--lease-grace",
        type=float,
        default=120.0,
        metavar="SECONDS",
        help="Slack added to the lease before an active session counts as expired.",
    )
    parser.add_argument(
        "--startup-grace",
        type=float,
        default=180.0,
        metavar="SECONDS",
        help="Minimum session age before it may be judged orphaned.",
    )
    parser.add_argument(
        "--max-terminations",
        type=int,
        default=25,
        help="Blast-radius bound on terminations per cycle.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Indent the JSON report instead of emitting one line per cycle.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Send worker diagnostics to stderr at INFO level.",
    )
    return parser


def resolve_schedule(args: argparse.Namespace) -> WorkerSchedule:
    if args.interval is None:
        if args.max_cycles is not None and args.max_cycles != 1:
            raise ValueError("--max-cycles above 1 requires --interval")
        return WorkerSchedule(max_cycles=1)
    max_cycles = args.max_cycles
    if max_cycles is None and args.max_runtime is None:
        max_cycles = DEFAULT_LOOP_CYCLES
    return WorkerSchedule(
        interval_seconds=args.interval,
        max_cycles=max_cycles,
        max_runtime_seconds=args.max_runtime,
    )


def emit(report: ReconciliationReport, *, pretty: bool) -> None:
    payload: dict[str, Any] = report.to_dict()
    if pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    sys.stdout.flush()


def build_worker(args: argparse.Namespace, settings: Settings) -> BrowserReconciliationWorker:
    policy = policy_from_settings(
        environment=args.environment or settings.app_env.value,
        session_timeout_seconds=(
            args.lease_ttl
            if args.lease_ttl is not None
            else settings.browserbase_session_timeout_seconds
        ),
        lease_grace_seconds=args.lease_grace,
        startup_grace_seconds=args.startup_grace,
        max_terminations=args.max_terminations,
        match_environment=not args.any_environment,
    )
    local_state = SqliteLocalSessionStore(
        args.database if args.database is not None else settings.operational_database_path,
        writable=args.execute,
    )
    return build_reconciliation_worker(
        settings,
        execute=args.execute,
        schedule=resolve_schedule(args),
        policy=policy,
        local_state=local_state,
        on_report=lambda report: emit(report, pretty=args.pretty),
    )


def install_signal_handlers(worker: BrowserReconciliationWorker) -> None:
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        signal_number = getattr(signal, name, None)
        if signal_number is None:
            continue
        try:
            loop.add_signal_handler(signal_number, worker.request_stop)
        except (NotImplementedError, RuntimeError, ValueError):
            # Signal handling is unavailable on this platform or thread.
            return


async def run(args: argparse.Namespace, settings: Settings) -> int:
    worker = build_worker(args, settings)
    install_signal_handlers(worker)
    reports = await worker.run()
    if not reports:
        print("No reconciliation cycle completed.", file=sys.stderr)
        return EXIT_PROVIDER_UNAVAILABLE
    if any(report.provider_error is not None for report in reports):
        return EXIT_PROVIDER_UNAVAILABLE
    if any(report.counts["failed"] for report in reports):
        return EXIT_FAILED_TERMINATION
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    # The report itself is printed to stdout by the sink; keep the worker's own
    # report logging out of stderr unless the operator asked for it.
    if not args.verbose:
        logging.getLogger("webaccessible.browser_reconciliation").setLevel(logging.WARNING)

    if args.any_environment and args.execute:
        parser.error(
            "--any-environment cannot be combined with --execute: sessions from another "
            "environment have no row in this operational database and would all look "
            "orphaned."
        )

    try:
        schedule = resolve_schedule(args)
    except ValueError as error:
        parser.error(str(error))

    settings = get_settings()
    if not settings.browserbase_configured:
        print(
            "Browserbase is not configured; set BROWSERBASE_API_KEY.",
            file=sys.stderr,
        )
        return EXIT_PROVIDER_UNAVAILABLE

    print(
        f"mode={'execute' if args.execute else 'dry_run'} "
        f"environment={args.environment or settings.app_env.value} "
        f"cycles={schedule.max_cycles} interval={schedule.interval_seconds}s",
        file=sys.stderr,
    )

    try:
        return asyncio.run(run(args, settings))
    except LocalStateUnavailableError as error:
        print(f"Operational state unavailable: {error}", file=sys.stderr)
        return EXIT_USAGE
    except BrowserbaseProviderError as error:
        print(f"Browserbase unavailable: {error.code.value}", file=sys.stderr)
        return EXIT_PROVIDER_UNAVAILABLE
    except ValueError as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
