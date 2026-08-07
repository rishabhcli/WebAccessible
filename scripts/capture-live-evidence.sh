#!/usr/bin/env bash

# Capture sanitized live evidence from a hosted WebAccessible deployment.
#
#   scripts/capture-live-evidence.sh https://app.example --output-dir evidence/2026-08-07
#
# The capture is read-only. It never requests a Live View URL, a CDP endpoint,
# EverOS memory contents, prompts, cookies, or uploaded documents, and it never
# writes to a provider or to Snowflake.
#
# Exit codes: 0 verified, 1 mandatory evidence missing or rehearsal,
# 2 usage or connection error, 3 a forbidden value was detected and redacted.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONNECTION="${SNOWFLAKE_CONNECTION:-webaccessible}"

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/capture-live-evidence.sh <app-url> --output-dir <dir> [options]

Required:
  <app-url>                    Hosted HTTPS application URL
  --output-dir <dir>           Directory for the manifest and report

Common options:
  --session-id <uuid>          Scope the capture to one WebAccessible session
  --skill-id <id>              Read identifiers for a specific EverOS skill
  --snowflake-connection <n>   Named connection (default: $SNOWFLAKE_CONNECTION or webaccessible)
  --streamlit-url <url>        Record an explicit Streamlit app URL
  --rehearsal                  Allow a non-public target; output is never qualifying

Environment:
  WEBACCESSIBLE_PARTICIPANT_TOKEN   Optional bearer token enabling read-only
                                    session, routine, and skill reads.
USAGE
}

if [[ $# -eq 0 ]]; then
  usage
  exit 2
fi

for argument in "$@"; do
  case "$argument" in
    -h | --help)
      usage
      exit 0
      ;;
  esac
done

if command -v uv >/dev/null 2>&1; then
  runner=(uv run --project "$ROOT_DIR" python -m tools.evidence)
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  runner=("$ROOT_DIR/.venv/bin/python" -m tools.evidence)
else
  printf 'uv or %s/.venv/bin/python is required. Run `make setup` first.\n' "$ROOT_DIR" >&2
  exit 2
fi

if [[ ! -f "$HOME/.snowflake/connections.toml" && -z "${SNOWFLAKE_HOME:-}" ]]; then
  printf 'Warning: no ~/.snowflake/connections.toml found. The named connection %s\n' "$CONNECTION" >&2
  printf 'must resolve for Snowflake evidence to be captured.\n' >&2
fi

export SNOWFLAKE_CONNECTION="$CONNECTION"

cd "$ROOT_DIR"
set +e
"${runner[@]}" "$@"
status=$?
set -e

case "$status" in
  0) printf 'Live evidence captured and verified.\n' ;;
  1) printf 'Capture incomplete: mandatory evidence is missing or this was a rehearsal.\n' >&2 ;;
  2) printf 'Capture could not start. Check the application URL and named connection.\n' >&2 ;;
  3) printf 'Capture blocked: a forbidden value was detected and redacted.\n' >&2 ;;
  *) printf 'Capture failed with status %s.\n' "$status" >&2 ;;
esac

exit "$status"
