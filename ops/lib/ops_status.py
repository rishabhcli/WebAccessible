#!/usr/bin/env python3
"""Shared status vocabulary, exit codes, and redacted reporting for ops checks.

Every WebAccessible ops check resolves to exactly one of five states. The states
are ordered by how much evidence the check actually collected, not by how the
operator feels about the result:

  unconfigured  Required configuration is absent. No provider call was possible.
  configured    Configuration is present. No live provider call was attempted or
                completed, so nothing about the provider itself is asserted.
  healthy       A live, read-only provider call succeeded. The provider answers.
  degraded      A live call was attempted and the provider is reachable or
                configured, but the observed state is impaired, partial, or over
                a documented limit.
  verified      Every assertion this specific check makes was satisfied against
                the live provider.

`verified` is always scoped to the narrow assertion named by the check. No check
in this directory verifies end-to-end product readiness, and every check prints
its evidence boundary so that its output cannot be quoted as a demo claim.

This module is imported by the Python checks. `ops_status.sh` mirrors the same
vocabulary and exit codes for the Bash checks.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ops_redact import redact  # noqa: E402


class OpsState(StrEnum):
    UNCONFIGURED = "unconfigured"
    CONFIGURED = "configured"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    VERIFIED = "verified"


# Lower exit code means more evidence was collected. `verified` is the only
# success code, so `set -e` callers stop unless the full assertion passed.
EXIT_CODES: Final[dict[OpsState, int]] = {
    OpsState.VERIFIED: 0,
    OpsState.HEALTHY: 10,
    OpsState.DEGRADED: 20,
    OpsState.CONFIGURED: 30,
    OpsState.UNCONFIGURED: 40,
}

EXIT_USAGE: Final = 2
EXIT_MISSING_PREREQUISITE: Final = 127

# Hosts that must never satisfy a cloud provider check. An ops check that would
# otherwise pass against one of these is a fixture, not evidence.
LOOPBACK_HOSTS: Final = frozenset(
    {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal", "[::1]"}
)


class LocalSubstitutionError(RuntimeError):
    """Raised when a check is pointed at a local or fixture endpoint."""


def reject_local_endpoint(label: str, value: str | None) -> None:
    """Refuse to treat a loopback or private endpoint as a cloud provider."""

    if not value:
        return
    lowered = value.strip().lower()
    host = lowered
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("@")[-1]
    if ":" in host and not host.startswith("["):
        host = host.rsplit(":", 1)[0]
    if host in LOOPBACK_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
        raise LocalSubstitutionError(
            f"{label} points at the local host. These checks never substitute a "
            f"local service or fixture for a cloud provider."
        )


class Report:
    """Collect redacted findings and resolve them into one ops state."""

    def __init__(self, check: str, provider: str, *, as_json: bool = False) -> None:
        self.check = check
        self.provider = provider
        self.as_json = as_json
        self.started_at = datetime.now(UTC)
        self._fields: list[tuple[str, str, Any]] = []
        self._findings: list[dict[str, str]] = []
        self._boundaries: list[str] = []
        self._sections: list[str] = []

    # -- collection -------------------------------------------------------

    def section(self, title: str) -> None:
        self._sections.append(title)
        if not self.as_json:
            print(f"\n== {title}")

    def field(self, label: str, value: Any, *, key: str | None = None) -> None:
        text = redact(_stringify(value))
        self._fields.append((key or label, label, _redact_value(value)))
        if not self.as_json:
            print(f"  {label}: {text}")

    def finding(self, level: str, message: str) -> None:
        """Record an observation. `level` is one of info, warn, fail."""

        if level not in {"info", "warn", "fail"}:
            raise ValueError(f"unsupported finding level {level!r}")
        clean = redact(message)
        self._findings.append({"level": level, "message": clean})
        if not self.as_json:
            print(f"  [{level}] {clean}")

    def boundary(self, statements: Iterable[str]) -> None:
        """Record what this check does NOT prove."""

        self._boundaries.extend(redact(statement) for statement in statements)

    # -- resolution -------------------------------------------------------

    @property
    def failures(self) -> list[str]:
        return [item["message"] for item in self._findings if item["level"] == "fail"]

    @property
    def warnings(self) -> list[str]:
        return [item["message"] for item in self._findings if item["level"] == "warn"]

    def conclude(self, state: OpsState, summary: str) -> int:
        """Print the verdict block and return the process exit code."""

        summary = redact(summary)
        if state is OpsState.VERIFIED and self.failures:
            raise AssertionError(
                "a check may not conclude 'verified' while failures are recorded"
            )
        code = EXIT_CODES[state]
        if self.as_json:
            print(
                json.dumps(
                    {
                        "check": self.check,
                        "provider": self.provider,
                        "state": str(state),
                        "summary": summary,
                        "exit_code": code,
                        "started_at": self.started_at.isoformat(),
                        "finished_at": datetime.now(UTC).isoformat(),
                        "fields": {key: value for key, _, value in self._fields},
                        "findings": self._findings,
                        "not_proven_by_this_check": self._boundaries,
                    },
                    indent=2,
                    sort_keys=False,
                )
            )
            return code
        print("\n== Verdict")
        print(f"  check: {self.check}")
        print(f"  provider: {self.provider}")
        print(f"  state: {state}")
        print(f"  summary: {summary}")
        if self._boundaries:
            print("\n== Not proven by this check")
            for statement in self._boundaries:
                print(f"  - {statement}")
        print(f"\nRESULT {self.check} {state} exit={code}")
        return code


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "unknown"
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(_redact_value(value), sort_keys=True)
    return str(value)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {str(k): _redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def fail_usage(message: str) -> int:
    print(f"usage error: {redact(message)}", file=sys.stderr)
    return EXIT_USAGE


def fail_prerequisite(message: str) -> int:
    print(f"missing prerequisite: {redact(message)}", file=sys.stderr)
    return EXIT_MISSING_PREREQUISITE


def load_env_file(path: str) -> dict[str, str]:
    """Read KEY=VALUE lines from an ignored env file without printing values."""

    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    values[key] = value
    except OSError:
        return {}
    return values
