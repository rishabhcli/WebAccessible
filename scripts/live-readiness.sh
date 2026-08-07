#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${1:-${API_PUBLIC_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"

if [[ ! "$BASE_URL" =~ ^https?:// ]]; then
  printf 'Readiness URL must begin with http:// or https://: %s\n' "$BASE_URL" >&2
  exit 2
fi

for command in curl python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf '%s is required.\n' "$command" >&2
    exit 127
  fi
done

health_file="$(mktemp)"
readiness_file="$(mktemp)"
trap 'rm -f "$health_file" "$readiness_file"' EXIT

printf 'Checking %s/health\n' "$BASE_URL"
curl --fail --silent --show-error \
  --connect-timeout 10 \
  --max-time 30 \
  --output "$health_file" \
  "$BASE_URL/health"

printf 'Checking %s/ready\n' "$BASE_URL"
curl --fail --silent --show-error \
  --connect-timeout 10 \
  --max-time 90 \
  --output "$readiness_file" \
  "$BASE_URL/ready"

python3 - "$health_file" "$readiness_file" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid JSON response in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


health = load_object(sys.argv[1])
readiness = load_object(sys.argv[2])
capabilities = readiness.get("capabilities")
if not isinstance(capabilities, dict):
    raise SystemExit("Readiness response has no capability map")

allowed_states = {
    "unconfigured",
    "configured",
    "reachable",
    "authorized",
    "unavailable",
    "capacity_exhausted",
}
required = ("browserbase", "everos", "snowflake", "guidance_model")
failures: list[str] = []

if health.get("status") != "ok":
    failures.append("health status is not ok")
if readiness.get("fixture_mode") is True:
    failures.append("fixture mode is active")
if readiness.get("ready") is not True:
    failures.append("top-level ready is false")

print(f"health: {health.get('status', 'missing')}")
print(f"mode: {readiness.get('mode', 'missing')}")
for name in required:
    capability = capabilities.get(name)
    if not isinstance(capability, dict):
        failures.append(f"{name} capability is missing")
        print(f"{name}: missing")
        continue
    state = capability.get("state")
    authorized = capability.get("authorized") is True
    print(f"{name}: state={state}, authorized={str(authorized).lower()}")
    if state not in allowed_states:
        failures.append(f"{name} returned unknown state {state!r}")
    if state != "authorized" or not authorized:
        failures.append(f"{name} is not authorized")

if failures:
    print("readiness: failed", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    raise SystemExit(1)

print("readiness: passed")
print(
    "This runtime check does not replace cold/warm run, termination, memory, telemetry, "
    "or Streamlit evidence."
)
PY
