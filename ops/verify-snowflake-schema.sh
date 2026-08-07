#!/usr/bin/env bash
#
# Verify that the Snowflake schema WebAccessible depends on is actually present
# and readable through the configured named Snowflake CLI connection.
#
#   ops/verify-snowflake-schema.sh [connection-name]
#
# Environment:
#   SNOWFLAKE_CONNECTION   Named connection. Default: webaccessible.
#   SNOWFLAKE_DATABASE     Default: WEBACCESSIBLE.
#   SNOWFLAKE_SCHEMA       Default: APP.
#   OPS_PROBE_VIEWS=0      Skip the per-view readability probe. Caps at healthy.
#   OPS_CHECK_STREAMLIT=0  Skip the reporting-surface inventory.
#   OPS_SHOW_ACCOUNT=1     Print the full account identifier instead of a mask.
#
# The expected objects are parsed out of snowflake/migrations/*.sql at run time,
# so this check cannot drift from the migrations it is meant to verify.
#
# Every statement issued here is read-only: SELECT against INFORMATION_SCHEMA,
# `SELECT ... WHERE 1 = 0` view probes that return no rows, SHOW commands, and
# one COUNT(*). Nothing is created, altered, dropped, merged, or inserted.
#
# Evidence model:
#   unconfigured  The named connection does not exist in the Snowflake CLI store.
#   configured    The connection exists but `snow connection test` failed, so no
#                 live statement was executed.
#   degraded      Connected, but the database or schema is invisible to the role,
#                 or an expected table or view is missing or does not compile.
#   healthy       Connected, the schema is visible, and every expected table and
#                 view is present. View readability was not probed.
#   verified      healthy PLUS every expected view returns a valid empty result
#                 set for the connection's role.

set -euo pipefail

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$OPS_DIR/.." && pwd)"
# shellcheck source=lib/ops_status.sh
source "$OPS_DIR/lib/ops_status.sh"

CHECK="snowflake-schema"
PROVIDER="snowflake"

ops_require_command snow python3

CONNECTION="${1:-${SNOWFLAKE_CONNECTION:-webaccessible}}"
DATABASE="${SNOWFLAKE_DATABASE:-WEBACCESSIBLE}"
SCHEMA="${SNOWFLAKE_SCHEMA:-APP}"
MIGRATIONS_DIR="$REPO_DIR/snowflake/migrations"
SCHEMA_RESULT="unknown"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

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
      SCHEMA) SCHEMA_RESULT="$rest" ;;
      *) ops_info "$line" ;;
    esac
  done
}

# Read a single scalar out of a `snow sql --format JSON` result document.
snow_scalar() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    print("unreadable")
    raise SystemExit(0)

rows = payload
if isinstance(rows, list) and rows and isinstance(rows[0], list):
    rows = [item for group in rows for item in group]
if not isinstance(rows, list):
    print("unreadable")
    raise SystemExit(0)

wanted = sys.argv[2].upper()
for row in rows:
    if not isinstance(row, dict):
        continue
    for key, value in row.items():
        if key.upper() == wanted or (wanted == "*COUNT*" and key.upper().startswith("COUNT")):
            print(value)
            raise SystemExit(0)
print("unreadable")
PY
}

snow_row_count() {
  python3 - "$1" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    print("unreadable")
    raise SystemExit(0)

rows = payload
if isinstance(rows, list) and rows and isinstance(rows[0], list):
    rows = [item for group in rows for item in group]
if not isinstance(rows, list):
    print("unreadable")
    raise SystemExit(0)
print(len([row for row in rows if isinstance(row, dict)]))
PY
}

printf 'WebAccessible Snowflake schema and view presence verification\n'
ops_section "Target"
ops_field "connection" "$CONNECTION"
ops_field "database" "$DATABASE"
ops_field "schema" "$SCHEMA"

# ---------------------------------------------------------------------------
# Expected object manifest, derived from the migrations in this repository.
# ---------------------------------------------------------------------------

ops_section "Expected objects"

if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  ops_fail "The migrations directory is missing: snowflake/migrations"
  ops_boundary "No object manifest could be derived, so nothing about Snowflake was asserted."
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_UNCONFIGURED" \
    "Run this check from a full checkout that contains snowflake/migrations."
fi

python3 - "$MIGRATIONS_DIR" >"$work_dir/expected.txt" <<'PY'
import re
import sys
from pathlib import Path

TABLE = re.compile(
    r"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_]+)", re.IGNORECASE | re.MULTILINE
)
VIEW = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_]+)",
    re.IGNORECASE | re.MULTILINE,
)

tables = []
views = []
for path in sorted(Path(sys.argv[1]).glob("*.sql")):
    body = path.read_text(encoding="utf-8")
    for name in TABLE.findall(body):
        if name.upper() not in tables:
            tables.append(name.upper())
    for name in VIEW.findall(body):
        if name.upper() not in views:
            views.append(name.upper())

for name in tables:
    print(f"TABLE {name}")
for name in views:
    print(f"VIEW {name}")
PY

EXPECTED_TABLES=()
EXPECTED_VIEWS=()
while IFS= read -r manifest_line; do
  case "$manifest_line" in
    "TABLE "*) EXPECTED_TABLES+=("${manifest_line#TABLE }") ;;
    "VIEW "*) EXPECTED_VIEWS+=("${manifest_line#VIEW }") ;;
  esac
done <"$work_dir/expected.txt"

ops_field "expected_tables" "${#EXPECTED_TABLES[@]}"
ops_field "expected_views" "${#EXPECTED_VIEWS[@]}"
ops_field "manifest_source" "snowflake/migrations/*.sql"

if (( ${#EXPECTED_TABLES[@]} == 0 )); then
  ops_fail "No CREATE TABLE statement was found in snowflake/migrations."
  ops_boundary "Without a manifest this check cannot assert schema completeness."
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_UNCONFIGURED" \
    "The migration files produced an empty object manifest."
fi

# ---------------------------------------------------------------------------
# Connection: does the named connection exist, and does it authenticate?
# ---------------------------------------------------------------------------

ops_section "Named connection"

if ! snow connection list --format JSON >"$work_dir/connections.json" 2>"$work_dir/connections.err"; then
  ops_warn "snow connection list failed; the connection store could not be read."
  ops_redact <"$work_dir/connections.err" | sed 's/^/        /'
  printf '[]' >"$work_dir/connections.json"
fi

set +e
python3 - "$work_dir/connections.json" "$CONNECTION" "${OPS_SHOW_ACCOUNT:-0}" \
  >"$work_dir/connection.txt" 2>&1 <<'PY'
import json
import sys
from pathlib import Path

LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}
SECRET_KEY_HINTS = ("password", "token", "private_key", "passcode", "secret")

try:
    entries = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    entries = []
wanted = sys.argv[2]
show_account = sys.argv[3] == "1"

if not isinstance(entries, list):
    entries = []

match = None
for entry in entries:
    if not isinstance(entry, dict):
        continue
    name = str(entry.get("connection_name") or entry.get("name") or "")
    if name == wanted:
        match = entry
        break

if match is None:
    print(f"FAIL The named connection {wanted!r} is not defined in the Snowflake CLI store.")
    print("SCHEMA unconfigured")
    raise SystemExit(0)

parameters = match.get("parameters")
if not isinstance(parameters, dict):
    parameters = {}


def mask(value):
    text = str(value)
    if show_account or len(text) <= 6:
        return text
    return f"{text[:3]}...{text[-3:]}"


# Identity fields only. Credential values are never read or printed; the account
# identifier is masked by default so ops output can be pasted into a ticket.
for key in ("account", "user", "role", "warehouse", "database", "schema", "authenticator"):
    value = parameters.get(key)
    if not value:
        continue
    print(f"FIELD connection.{key} {mask(value) if key == 'account' else value}")

host = str(parameters.get("host") or parameters.get("account") or "").lower()
bare = host.split("://")[-1].split("/")[0].split(":")[0]
if bare in LOOPBACK or bare.endswith(".local") or bare.endswith(".localhost"):
    print(
        "FAIL The named connection points at a local host. A local stand-in is never "
        "accepted as Snowflake evidence."
    )
    print("SCHEMA unconfigured")
    raise SystemExit(0)

credential_keys = sorted(
    key for key in parameters if any(hint in key.lower() for hint in SECRET_KEY_HINTS)
)
if credential_keys:
    print(f"FIELD connection.credential_kind {','.join(credential_keys)}")
else:
    print("WARN The connection defines no password, token, or key parameter.")

print("SCHEMA defined")
PY
set -e
consume_report <"$work_dir/connection.txt"

if [[ "$SCHEMA_RESULT" == "unconfigured" ]]; then
  ops_boundary "No live Snowflake statement was executed."
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_UNCONFIGURED" \
    "Define the connection, then re-run: snow connection add --connection-name $CONNECTION"
fi

if ! snow connection test --connection "$CONNECTION" >"$work_dir/test.txt" 2>&1; then
  ops_fail "snow connection test failed for connection $CONNECTION."
  ops_redact <"$work_dir/test.txt" | sed 's/^/        /'
  ops_boundary "The connection is defined but did not authenticate, so no schema state was observed."
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_CONFIGURED" \
    "The named connection exists but did not authenticate."
fi
ops_info "snow connection test succeeded."

# ---------------------------------------------------------------------------
# Presence: compare INFORMATION_SCHEMA against the derived manifest.
# ---------------------------------------------------------------------------

ops_section "Object presence"

PRESENCE_SQL="SELECT TABLE_NAME AS NAME, TABLE_TYPE AS KIND
FROM ${DATABASE}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '${SCHEMA}'
ORDER BY TABLE_NAME;"

if ! snow sql --connection "$CONNECTION" --format JSON --query "$PRESENCE_SQL" \
  >"$work_dir/presence.json" 2>"$work_dir/presence.err"; then
  ops_fail "The INFORMATION_SCHEMA query failed. The role may not see ${DATABASE}.${SCHEMA}."
  ops_redact <"$work_dir/presence.err" | sed 's/^/        /'
  ops_boundary "Object presence was not observed."
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_DEGRADED" \
    "Connected, but ${DATABASE}.${SCHEMA} could not be inspected by this role."
fi

set +e
python3 - "$work_dir/presence.json" "$work_dir/expected.txt" >"$work_dir/presence.txt" 2>&1 <<'PY'
import json
import sys
from pathlib import Path


def result_rows(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, list):
        if payload and isinstance(payload[0], list):
            flattened = []
            for group in payload:
                if isinstance(group, list):
                    flattened.extend(item for item in group if isinstance(item, dict))
            return flattened
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return None


def field(row, *names):
    for name in names:
        for key in (name, name.upper(), name.lower()):
            if key in row:
                return str(row[key] or "")
    return ""


observed = result_rows(sys.argv[1])
if observed is None:
    print("FAIL The INFORMATION_SCHEMA response could not be parsed as JSON rows.")
    print("SCHEMA unreadable")
    raise SystemExit(0)

if not observed:
    print("FAIL The schema contains no objects visible to this role.")
    print("SCHEMA empty")
    raise SystemExit(0)

present_tables = set()
present_views = set()
for row in observed:
    name = field(row, "NAME", "TABLE_NAME").upper()
    kind = field(row, "KIND", "TABLE_TYPE").upper()
    if not name:
        continue
    if "VIEW" in kind:
        present_views.add(name)
    else:
        present_tables.add(name)

expected_tables = []
expected_views = []
for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
    kind, _, name = line.partition(" ")
    if kind == "TABLE":
        expected_tables.append(name)
    elif kind == "VIEW":
        expected_views.append(name)

print(f"FIELD present_tables {len(present_tables)}")
print(f"FIELD present_views {len(present_views)}")

missing_tables = [name for name in expected_tables if name not in present_tables]
missing_views = [name for name in expected_views if name not in present_views]

for name in expected_tables:
    if name in present_tables:
        print(f"INFO table {name} present")
for name in expected_views:
    if name in present_views:
        print(f"INFO view {name} present")
for name in missing_tables:
    print(f"FAIL The expected table {name} is missing from the schema.")
for name in missing_views:
    print(f"FAIL The expected view {name} is missing from the schema.")

extra_views = sorted(present_views - set(expected_views))
if extra_views:
    print(f"INFO views present but absent from the migrations: {', '.join(extra_views)}")

print("SCHEMA incomplete" if (missing_tables or missing_views) else "SCHEMA complete")
PY
set -e
consume_report <"$work_dir/presence.txt"

if [[ "$SCHEMA_RESULT" != "complete" ]]; then
  ops_boundary "A present table proves the migration ran. It does not prove the table holds a backend-created row."
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_DEGRADED" \
    "The schema is reachable but incomplete. Re-apply: SNOWFLAKE_CONNECTION=$CONNECTION ./scripts/apply-snowflake.sh"
fi

# ---------------------------------------------------------------------------
# Readability probe: does each view actually compile for this role?
# ---------------------------------------------------------------------------

ops_section "View readability"

VIEWS_READABLE=0
if [[ "${OPS_PROBE_VIEWS:-1}" == "0" ]]; then
  ops_info "OPS_PROBE_VIEWS=0; the per-view readability probe was skipped by request."
elif (( ${#EXPECTED_VIEWS[@]} == 0 )); then
  ops_info "The migrations define no views to probe."
else
  for view_name in "${EXPECTED_VIEWS[@]}"; do
    if snow sql --connection "$CONNECTION" --format JSON \
      --query "SELECT 1 AS PROBE FROM ${DATABASE}.${SCHEMA}.${view_name} WHERE 1 = 0;" \
      >"$work_dir/probe.json" 2>"$work_dir/probe.err"; then
      VIEWS_READABLE=$((VIEWS_READABLE + 1))
    else
      ops_fail "The view $view_name is present but does not compile for this role."
      ops_redact <"$work_dir/probe.err" | sed 's/^/        /'
    fi
  done
  ops_field "views_readable" "${VIEWS_READABLE}/${#EXPECTED_VIEWS[@]}"
fi

# ---------------------------------------------------------------------------
# Context: reporting surface and rate-card rows. Reported, never fabricated.
# ---------------------------------------------------------------------------

if [[ "${OPS_CHECK_STREAMLIT:-1}" != "0" ]]; then
  ops_section "Reporting surface"

  if snow sql --connection "$CONNECTION" --format JSON \
    --query "SHOW STREAMLITS IN SCHEMA ${DATABASE}.${SCHEMA};" \
    >"$work_dir/streamlit.json" 2>"$work_dir/streamlit.err"; then
    STREAMLIT_COUNT="$(snow_row_count "$work_dir/streamlit.json")"
    ops_field "streamlit_entities" "$STREAMLIT_COUNT"
    if [[ "$STREAMLIT_COUNT" == "0" ]]; then
      ops_warn "No Streamlit entity exists in ${DATABASE}.${SCHEMA}. See docs/operations/runbook-streamlit-deploy-failure.md."
    fi
  else
    ops_warn "SHOW STREAMLITS failed; the reporting surface could not be inventoried."
    ops_redact <"$work_dir/streamlit.err" | sed 's/^/        /'
  fi

  if snow sql --connection "$CONNECTION" --format JSON \
    --query "SELECT COUNT(*) AS RATE_CARD_ROWS FROM ${DATABASE}.${SCHEMA}.COST_RATE_CARDS;" \
    >"$work_dir/rates.json" 2>/dev/null; then
    RATE_CARD_ROWS="$(snow_scalar "$work_dir/rates.json" "RATE_CARD_ROWS")"
    ops_field "cost_rate_card_rows" "$RATE_CARD_ROWS"
    if [[ "$RATE_CARD_ROWS" == "0" ]]; then
      ops_warn "COST_RATE_CARDS is empty. Cost calculation reports 'unavailable' and the cost proof stays blocked."
    fi
  else
    ops_warn "COST_RATE_CARDS could not be counted."
  fi
fi

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

ops_boundary "Object presence proves the migrations were applied. It does not prove any backend-created, non-fixture row exists in SESSION_RUNS, SESSION_STEPS, MODEL_CALLS, or MODEL_COSTS."
ops_boundary "A readable view is not a populated view. An empty evidence view must report 'No verified data', never a sample metric."
ops_boundary "This check makes no Cortex call, so it says nothing about guidance-model availability or token accounting."
ops_boundary "ACCOUNT_USAGE remains reconciliation and backfill only; it is never the live cost source."

if (( ${#OPS_FAILURES[@]} )); then
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_DEGRADED" \
    "${#OPS_FAILURES[@]} schema failure(s). Re-apply: SNOWFLAKE_CONNECTION=$CONNECTION ./scripts/apply-snowflake.sh"
fi

if [[ "${OPS_PROBE_VIEWS:-1}" == "0" ]]; then
  ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_HEALTHY" \
    "All expected tables and views are present. View readability was not probed, so the schema is not verified."
fi

ops_conclude "$CHECK" "$PROVIDER" "$OPS_STATE_VERIFIED" \
  "All ${#EXPECTED_TABLES[@]} expected tables and ${#EXPECTED_VIEWS[@]} expected views are present and readable by the connection role."
