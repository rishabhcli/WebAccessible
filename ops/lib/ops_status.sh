# shellcheck shell=bash
#
# Shared status vocabulary, exit codes, and redaction for the Bash ops checks.
# Mirrors ops/lib/ops_status.py. Source it, never execute it:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/ops_status.sh"
#
# The five states are ordered by how much evidence a check collected:
#   unconfigured < configured < degraded < healthy < verified
# `verified` is always scoped to the narrow assertion the check names, and every
# check must print an evidence boundary saying what it does not prove.

OPS_STATE_UNCONFIGURED="unconfigured"
OPS_STATE_CONFIGURED="configured"
OPS_STATE_HEALTHY="healthy"
OPS_STATE_DEGRADED="degraded"
OPS_STATE_VERIFIED="verified"

OPS_EXIT_VERIFIED=0
OPS_EXIT_HEALTHY=10
OPS_EXIT_DEGRADED=20
OPS_EXIT_CONFIGURED=30
OPS_EXIT_UNCONFIGURED=40
OPS_EXIT_USAGE=2
OPS_EXIT_MISSING_PREREQUISITE=127

OPS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_REDACT="$OPS_LIB_DIR/ops_redact.py"

# Collected findings. `fail` findings make a `verified` verdict impossible.
OPS_FAILURES=()
OPS_WARNINGS=()
OPS_BOUNDARIES=()

ops_state_exit_code() {
  case "$1" in
    "$OPS_STATE_VERIFIED") printf '%s' "$OPS_EXIT_VERIFIED" ;;
    "$OPS_STATE_HEALTHY") printf '%s' "$OPS_EXIT_HEALTHY" ;;
    "$OPS_STATE_DEGRADED") printf '%s' "$OPS_EXIT_DEGRADED" ;;
    "$OPS_STATE_CONFIGURED") printf '%s' "$OPS_EXIT_CONFIGURED" ;;
    "$OPS_STATE_UNCONFIGURED") printf '%s' "$OPS_EXIT_UNCONFIGURED" ;;
    *) printf '%s' "$OPS_EXIT_USAGE" ;;
  esac
}

# Filter stdin through the single shared redaction implementation. Use this for
# every provider or CLI output block before it reaches a terminal or a log.
ops_redact() {
  if [[ -x "$OPS_REDACT" || -f "$OPS_REDACT" ]]; then
    python3 "$OPS_REDACT"
  else
    printf '%s\n' "ops_redact.py is missing; refusing to print unredacted output" >&2
    cat >/dev/null
    return 1
  fi
}

ops_redact_text() {
  printf '%s' "$1" | ops_redact
}

ops_section() {
  printf '\n== %s\n' "$1"
}

ops_field() {
  printf '  %s: %s\n' "$1" "$(ops_redact_text "${2-}")"
}

ops_info() {
  printf '  [info] %s\n' "$(ops_redact_text "$1")"
}

ops_warn() {
  OPS_WARNINGS+=("$1")
  printf '  [warn] %s\n' "$(ops_redact_text "$1")"
}

ops_fail() {
  OPS_FAILURES+=("$1")
  printf '  [fail] %s\n' "$(ops_redact_text "$1")"
}

ops_boundary() {
  OPS_BOUNDARIES+=("$1")
}

ops_require_command() {
  local missing=0 command_name
  for command_name in "$@"; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
      printf 'missing prerequisite: %s is required and was not found on PATH.\n' \
        "$command_name" >&2
      missing=1
    fi
  done
  if (( missing )); then
    exit "$OPS_EXIT_MISSING_PREREQUISITE"
  fi
}

ops_usage_error() {
  printf 'usage error: %s\n' "$(ops_redact_text "$1")" >&2
  exit "$OPS_EXIT_USAGE"
}

# Refuse to accept a loopback or fixture endpoint as evidence about a cloud
# provider. Requirement: never substitute a local service for a cloud provider.
ops_reject_local_endpoint() {
  local label="$1" value="${2-}" host
  [[ -z "$value" ]] && return 0
  host="${value#*://}"
  host="${host%%/*}"
  host="${host##*@}"
  host="${host%%\?*}"
  case "$host" in
    *:*) [[ "$host" == \[* ]] || host="${host%:*}" ;;
  esac
  case "$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')" in
    localhost|127.0.0.1|0.0.0.0|::1|\[::1\]|host.docker.internal|*.local|*.localhost)
      ops_usage_error "$label points at the local host. These checks never substitute a local service or fixture for a cloud provider."
      ;;
  esac
}

# Print the verdict block and exit. Refuses to report `verified` if any `fail`
# finding was recorded, so an operator cannot accidentally over-claim.
ops_conclude() {
  local check="$1" provider="$2" state="$3" summary="$4" code statement

  if [[ "$state" == "$OPS_STATE_VERIFIED" && ${#OPS_FAILURES[@]} -gt 0 ]]; then
    printf 'internal error: cannot conclude verified with %d failures\n' \
      "${#OPS_FAILURES[@]}" >&2
    state="$OPS_STATE_DEGRADED"
  fi
  code="$(ops_state_exit_code "$state")"

  ops_section "Verdict"
  ops_field "check" "$check"
  ops_field "provider" "$provider"
  ops_field "state" "$state"
  ops_field "summary" "$summary"

  if (( ${#OPS_BOUNDARIES[@]} )); then
    ops_section "Not proven by this check"
    for statement in "${OPS_BOUNDARIES[@]}"; do
      printf '  - %s\n' "$(ops_redact_text "$statement")"
    done
  fi

  printf '\nRESULT %s %s exit=%s\n' "$check" "$state" "$code"
  exit "$code"
}
