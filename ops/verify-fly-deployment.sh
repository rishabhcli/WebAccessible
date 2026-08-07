#!/usr/bin/env bash
#
# Verify the WebAccessible Fly deployment against the live hosted URL.
#
#   ops/verify-fly-deployment.sh [https://host]
#
# Environment:
#   FLY_APP             Fly app name. Default: webaccessible-care (fly.toml).
#   OPS_PUBLIC_URL      Hosted base URL. Default: API_PUBLIC_URL, else
#                       https://<FLY_APP>.fly.dev.
#   OPS_EXPECT_IMAGE    Substring of the expected deployed image ref or digest.
#                       Read from Fly, so this is the assertable revision pin.
#   OPS_EXPECT_COMMIT   Expected BUILD_COMMIT. Only assertable if the hosted
#                       process exposes it; the current /health and /ready
#                       contracts do not, so setting it caps the verdict at
#                       `healthy` rather than silently passing.
#   OPS_SKIP_FLYCTL=1   Skip the platform layer. Caps the verdict at `healthy`.
#
# This check reads only. It never deploys, restarts, scales, or mutates state.
#
# Evidence model:
#   unconfigured  No app name resolved, or no hosted URL to probe.
#   configured    A hosted URL exists but nothing answered and no machine
#                 evidence was obtainable.
#   degraded      Something answered but health, readiness, the served bundle,
#                 or a machine state is wrong.
#   healthy       /health, /ready, and the served UI all answered correctly over
#                 the public HTTPS URL.
#   verified      healthy PLUS Fly platform evidence: at least one `app` machine
#                 started, a readable current release and image, and a matching
#                 revision pin when one was requested.
#
# `verified` means this deployment serves the expected revision. It proves no
# provider round trip. The script prints its own evidence boundary.

set -euo pipefail

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$OPS_DIR/.." && pwd)"
# shellcheck source=lib/ops_status.sh
source "$OPS_DIR/lib/ops_status.sh"

CHECK="fly-deployment"
PROVIDER="fly.io"

ops_require_command curl python3

FLY_APP="${FLY_APP:-webaccessible-care}"
BASE_URL="${1:-${OPS_PUBLIC_URL:-${API_PUBLIC_URL:-https://${FLY_APP}.fly.dev}}}"
BASE_URL="${BASE_URL%/}"
CONNECT_TIMEOUT="${OPS_CONNECT_TIMEOUT:-10}"
READY_TIMEOUT="${OPS_READY_TIMEOUT:-90}"

if [[ -z "$FLY_APP" || -z "$BASE_URL" ]]; then
  ops_section "Configuration"
  ops_fail "No Fly app name or hosted URL is configured."
  ops_boundary "Nothing about the hosted deployment was observed."
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_UNCONFIGURED" \
    "Set FLY_APP and OPS_PUBLIC_URL, then re-run."
fi

if [[ ! "$BASE_URL" =~ ^https:// ]]; then
  ops_usage_error "The hosted URL must be https. Plain http cannot evidence the force_https service defined in fly.toml."
fi
ops_reject_local_endpoint "The hosted URL" "$BASE_URL"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

# Route parser output through the shared vocabulary. Lines are tagged FIELD,
# INFO, WARN, FAIL, or a check-specific keyword.
consume_report() {
  local line keyword rest
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    keyword="${line%% *}"
    rest="${line#* }"
    case "$keyword" in
      FIELD) ops_field "${rest%% *}" "${rest#* }" ;;
      INFO) ops_info "$rest" ;;
      WARN) ops_warn "$rest" ;;
      FAIL) ops_fail "$rest" ;;
      PLATFORM) PLATFORM_EVIDENCE="$rest" ;;
      READY) READY_OK="$rest" ;;
      COMMIT) COMMIT_RESULT="$rest" ;;
      IMAGE) IMAGE_RESULT="$rest" ;;
      *) ops_info "$line" ;;
    esac
  done
}

printf 'WebAccessible Fly deployment verification\n'
ops_section "Target"
ops_field "app" "$FLY_APP"
ops_field "base_url" "$BASE_URL"
ops_field "expected_image" "${OPS_EXPECT_IMAGE:-not asserted}"
ops_field "expected_build_commit" "${OPS_EXPECT_COMMIT:-not asserted}"

# ---------------------------------------------------------------------------
# Platform layer. Optional, but required for a `verified` verdict.
# ---------------------------------------------------------------------------

PLATFORM_EVIDENCE="unavailable"
IMAGE_RESULT="not_asserted"
READY_OK="not_ok"
COMMIT_RESULT="not_asserted"

ops_section "Fly platform"

if [[ "${OPS_SKIP_FLYCTL:-0}" == "1" ]]; then
  ops_info "OPS_SKIP_FLYCTL=1; the platform layer was skipped by request."
elif ! command -v flyctl >/dev/null 2>&1; then
  ops_warn "flyctl is not on PATH. Machine, release, and image evidence is unavailable."
elif ! flyctl status --app "$FLY_APP" --json >"$work_dir/status.json" 2>"$work_dir/status.err"; then
  ops_warn "flyctl status failed for app $FLY_APP. Confirm authentication with 'flyctl auth whoami'."
  ops_redact <"$work_dir/status.err" | sed 's/^/        /'
else
  flyctl releases --app "$FLY_APP" --json >"$work_dir/releases.json" 2>/dev/null \
    || printf '[]' >"$work_dir/releases.json"
  flyctl image show --app "$FLY_APP" --json >"$work_dir/image.json" 2>/dev/null \
    || printf '{}' >"$work_dir/image.json"

  set +e
  python3 - "$work_dir/status.json" "$work_dir/releases.json" "$work_dir/image.json" \
    "$REPO_DIR/fly.toml" "${OPS_EXPECT_IMAGE:-}" >"$work_dir/platform.txt" 2>&1 <<'PY'
import json
import re
import sys
from pathlib import Path


def load(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


status = load(sys.argv[1], None)
releases = load(sys.argv[2], [])
image = load(sys.argv[3], {})
fly_toml_path = Path(sys.argv[4])
expected_image = sys.argv[5]

expected_region = ""
if fly_toml_path.is_file():
    match = re.search(
        r'^primary_region\s*=\s*"([^"]+)"',
        fly_toml_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match:
        expected_region = match.group(1)

if not isinstance(status, dict):
    print("FAIL flyctl status did not return a JSON object.")
    print("PLATFORM unavailable")
    raise SystemExit(0)

raw_machines = status.get("Machines") or status.get("machines") or []
machines = []
for machine in raw_machines if isinstance(raw_machines, list) else []:
    if not isinstance(machine, dict):
        continue
    config = machine.get("config") or machine.get("Config") or {}
    metadata = config.get("metadata") if isinstance(config, dict) else {}
    process = ""
    if isinstance(metadata, dict):
        process = str(metadata.get("fly_process_group") or "")
    machines.append(
        {
            "id": str(machine.get("id") or machine.get("ID") or "unknown"),
            "state": str(machine.get("state") or machine.get("State") or "unknown"),
            "region": str(machine.get("region") or machine.get("Region") or "unknown"),
            "process": process or "app",
        }
    )

started = [m for m in machines if m["state"] == "started" and m["process"] == "app"]

print(f"FIELD machine_count {len(machines)}")
print(f"FIELD started_app_machines {len(started)}")
print(f"FIELD primary_region {expected_region or 'unknown'}")
for machine in machines:
    print(
        f"INFO machine {machine['id']} process={machine['process']} "
        f"state={machine['state']} region={machine['region']}"
    )

if not started:
    print("FAIL No Fly machine in the 'app' process group is in state 'started'.")

off_region = sorted({m["region"] for m in started if expected_region and m["region"] != expected_region})
if off_region:
    print(f"WARN Started machines run outside the primary region: {', '.join(off_region)}.")

# fly.toml requires one always-running machine.
if len(started) < 1:
    print("WARN fly.toml sets min_machines_running = 1; no started machine satisfies it.")

current = None
if isinstance(releases, list):
    for release in releases:
        if isinstance(release, dict):
            current = release
            break

release_ok = False
if isinstance(current, dict):
    version = current.get("Version", current.get("version"))
    stable = current.get("Stable", current.get("stable"))
    status_text = current.get("Status", current.get("status")) or "unknown"
    print(f"FIELD current_release v{version}")
    print(f"FIELD current_release_status {status_text}")
    if stable is False:
        print("WARN The most recent Fly release is not marked stable.")
    release_ok = True
else:
    print("WARN No Fly release record was readable; rollback targets must be listed manually.")

deployed_ref = ""
if isinstance(image, dict):
    for key in ("Ref", "ref", "Digest", "digest", "Tag", "tag"):
        value = image.get(key)
        if isinstance(value, str) and value:
            deployed_ref = value
            break
if deployed_ref:
    print(f"FIELD deployed_image {deployed_ref}")
else:
    print("WARN The deployed image reference was not readable.")

if expected_image:
    if not deployed_ref:
        print("FAIL OPS_EXPECT_IMAGE was set but no deployed image reference could be read.")
        print("IMAGE unmatched")
    elif expected_image in deployed_ref:
        print("IMAGE matched")
    else:
        print("FAIL The deployed image does not contain OPS_EXPECT_IMAGE.")
        print("IMAGE mismatched")
else:
    print("IMAGE not_asserted")

if started and release_ok:
    print("PLATFORM ok")
elif started or release_ok:
    print("PLATFORM partial")
else:
    print("PLATFORM unavailable")
PY
  platform_rc=$?
  set -e
  (( platform_rc != 0 )) && ops_warn "The Fly platform parser exited $platform_rc."
  consume_report <"$work_dir/platform.txt"
fi

ops_field "platform_evidence" "$PLATFORM_EVIDENCE"

# ---------------------------------------------------------------------------
# HTTP layer against the live hosted URL.
# ---------------------------------------------------------------------------

ops_section "Hosted HTTPS endpoints"

fetch() {
  # fetch <path> <max-time> <body-file>; prints "<http_code> <seconds>"
  local path="$1" max_time="$2" body_file="$3" result
  result="$(
    curl --silent --show-error --location \
      --connect-timeout "$CONNECT_TIMEOUT" \
      --max-time "$max_time" \
      --output "$body_file" \
      --write-out '%{http_code} %{time_total}' \
      "${BASE_URL}${path}" 2>>"$work_dir/curl.err" || true
  )"
  [[ -z "$result" ]] && result="000 0"
  printf '%s\n' "$result"
}

: >"$work_dir/curl.err"
read -r health_code health_time <<<"$(fetch "/health" 30 "$work_dir/health.json")"
read -r ready_code ready_time <<<"$(fetch "/ready" "$READY_TIMEOUT" "$work_dir/ready.json")"
read -r root_code root_time <<<"$(fetch "/" 30 "$work_dir/root.html")"

ops_field "GET /health" "HTTP $health_code in ${health_time}s"
ops_field "GET /ready" "HTTP $ready_code in ${ready_time}s"
ops_field "GET /" "HTTP $root_code in ${root_time}s"

if [[ "$health_code" == "000" && "$ready_code" == "000" && "$root_code" == "000" ]]; then
  ops_fail "The hosted URL did not answer. No HTTP evidence was collected."
  ops_redact <"$work_dir/curl.err" | sed 's/^/        /'
  ops_boundary "No hosted response was observed, so no provider capability was checked."
  ops_boundary "A silent URL does not distinguish a stopped machine from a DNS or TLS fault."
  if [[ "$PLATFORM_EVIDENCE" == "unavailable" ]]; then
    ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_CONFIGURED" \
      "App and URL are configured; neither Fly nor the hosted URL produced evidence."
  fi
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_DEGRADED" \
    "Fly reports machines but the hosted URL served nothing. See docs/operations/runbook-fly-restart.md."
fi

set +e
python3 - "$work_dir/health.json" "$work_dir/ready.json" "$work_dir/root.html" \
  "$health_code" "$ready_code" "$root_code" "${OPS_EXPECT_COMMIT:-}" \
  >"$work_dir/http.txt" 2>&1 <<'PY'
import json
import sys
from pathlib import Path

health_path, ready_path, root_path = sys.argv[1:4]
health_code, ready_code, root_code = sys.argv[4:7]
expected_commit = sys.argv[7]

ALLOWED_PROVIDER_STATES = {
    "unconfigured",
    "configured",
    "reachable",
    "authorized",
    "unavailable",
    "capacity_exhausted",
}
REQUIRED_CAPABILITIES = ("browserbase", "everos", "snowflake", "guidance_model")
LIVE_PROVIDER_STATES = {"reachable", "authorized"}


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


health = load_json(health_path)
if health_code != "200":
    print(f"FAIL /health returned HTTP {health_code}.")
elif not isinstance(health, dict):
    print("FAIL /health did not return a JSON object.")
else:
    print(f"FIELD health_status {health.get('status', 'missing')}")
    print(f"FIELD health_service {health.get('service', 'missing')}")
    print(f"FIELD served_version {health.get('version', 'missing')}")
    if health.get("status") != "ok":
        print("FAIL /health reports a status other than ok.")
    if health.get("service") != "webaccessible-api":
        print("FAIL /health is not served by the webaccessible-api service.")

try:
    root_body = Path(root_path).read_text(encoding="utf-8", errors="replace")
except OSError:
    root_body = ""
if root_code != "200":
    print(f"FAIL The hosted root path returned HTTP {root_code}; the web bundle is not served.")
elif "<script" not in root_body and "<div id=" not in root_body:
    print("FAIL The hosted root path returned no HTML application shell.")
else:
    print(f"FIELD served_web_bundle yes,{len(root_body)}_bytes")

readiness = load_json(ready_path)
ready_ok = False
if ready_code != "200":
    print(f"FAIL /ready returned HTTP {ready_code}.")
elif not isinstance(readiness, dict):
    print("FAIL /ready did not return a JSON object.")
else:
    mode = readiness.get("mode", "missing")
    fixture_mode = readiness.get("fixture_mode")
    print(f"FIELD runtime_mode {mode}")
    print(f"FIELD fixture_mode {str(bool(fixture_mode)).lower()}")
    print(f"FIELD ready_flag {str(readiness.get('ready')).lower()}")

    if fixture_mode is True:
        print("FAIL The hosted app reports fixture_mode. A fixture deployment is not evidence.")
    if mode not in {"demo", "production"}:
        print(f"WARN The hosted runtime mode is {mode!r}, not demo or production.")

    capabilities = readiness.get("capabilities")
    if not isinstance(capabilities, dict):
        print("FAIL /ready returned no capability map.")
    else:
        live = 0
        for name in REQUIRED_CAPABILITIES:
            capability = capabilities.get(name)
            if not isinstance(capability, dict):
                print(f"FAIL The /ready capability {name} is missing.")
                continue
            state = capability.get("state")
            configured = str(bool(capability.get("configured"))).lower()
            authorized = str(bool(capability.get("authorized"))).lower()
            print(
                f"FIELD capability.{name} state={state},configured={configured},"
                f"authorized={authorized}"
            )
            if state not in ALLOWED_PROVIDER_STATES:
                print(f"FAIL The capability {name} returned the unknown state {state!r}.")
            elif state in LIVE_PROVIDER_STATES:
                live += 1
            elif state == "unconfigured":
                print(f"WARN The capability {name} is unconfigured in the hosted process.")
            elif state == "capacity_exhausted":
                print(
                    f"WARN The capability {name} reports capacity_exhausted. "
                    "See docs/operations/runbook-browserbase-exhaustion.md."
                )
            else:
                print(f"WARN The capability {name} reports {state!r}.")
        print(f"FIELD live_capabilities {live}/{len(REQUIRED_CAPABILITIES)}")
        ready_ok = readiness.get("ready") is True and fixture_mode is not True

    build_commit = readiness.get("build_commit") or (health or {}).get("build_commit")
    if expected_commit:
        if not build_commit:
            print(
                "WARN The hosted /health and /ready contracts expose no build_commit, so the "
                "deployed revision cannot be matched over HTTP. Pin the revision with "
                "OPS_EXPECT_IMAGE instead."
            )
            print("COMMIT unmatched")
        elif str(build_commit).startswith(expected_commit):
            print(f"FIELD build_commit {build_commit}")
            print("COMMIT matched")
        else:
            print(f"FIELD build_commit {build_commit}")
            print("FAIL The hosted build_commit does not match OPS_EXPECT_COMMIT.")
            print("COMMIT mismatched")
    else:
        print("COMMIT not_asserted")

print("READY ok" if ready_ok else "READY not_ok")
PY
http_rc=$?
set -e
(( http_rc != 0 )) && ops_warn "The hosted-response parser exited $http_rc."
consume_report <"$work_dir/http.txt"

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

ops_boundary "A green /health and /ready prove the process answers. They do not prove a Browserbase create/attach/terminate round trip, an EverOS write and readback, a backend-created Snowflake row, or a Cortex call."
ops_boundary "The Browserbase capability in /ready reports 'authorized' only while a WebAccessible-owned session is attached; an idle deployment reporting 'configured' is expected, not a fault."
ops_boundary "Deployment verification is not demo readiness. The remaining live gates are listed in docs/SETUP_STATUS.md."
ops_boundary "This check reads only. It does not prove that a rollback or restart would succeed."

if (( ${#OPS_FAILURES[@]} )); then
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_DEGRADED" \
    "${#OPS_FAILURES[@]} deployment failure(s) recorded. See docs/operations/runbook-fly-restart.md."
fi

if [[ "$READY_OK" != "ok" ]]; then
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_DEGRADED" \
    "The hosted endpoints answered but /ready is not true. Providers, not the deployment, are the likely cause."
fi

if [[ "$PLATFORM_EVIDENCE" != "ok" ]]; then
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_HEALTHY" \
    "Hosted HTTPS evidence is complete. Fly machine or release evidence is missing, so the deployment is not verified."
fi

if [[ "$IMAGE_RESULT" == "unmatched" || "$IMAGE_RESULT" == "mismatched" ]]; then
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_DEGRADED" \
    "The deployed image does not satisfy OPS_EXPECT_IMAGE."
fi

if [[ -n "${OPS_EXPECT_COMMIT:-}" && "$COMMIT_RESULT" != "matched" ]]; then
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_HEALTHY" \
    "Hosted and platform evidence are complete, but the deployed build_commit could not be matched over HTTP."
fi

ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_VERIFIED" \
  "The hosted URL serves the expected application from a started Fly machine on a readable release."
