#!/usr/bin/env bash

# Idempotent deployment for the isolated Cortex Analyst caregiver reporting application.
#
# Every step converges on the same state when run repeatedly:
#   1. Static YAML/Python validation of the semantic model (no Snowflake connection).
#   2. CREATE SCHEMA IF NOT EXISTS / CREATE STAGE IF NOT EXISTS.
#   3. CREATE OR REPLACE VIEW for the redacted projection layer.
#   4. SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML with verify_only=TRUE, then for real.
#   5. Optional grants, only when ANALYST_APPLY_GRANTS=1.
#   6. snow streamlit deploy against snowflake/analyst/snowflake.yml only.
#
# This script never touches WEBACCESSIBLE.APP objects or the already-live
# WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER Streamlit entity.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANALYST_DIR="$ROOT_DIR/snowflake/analyst"
CONNECTION="${SNOWFLAKE_CONNECTION:-webaccessible}"
ENTITY="${SNOWFLAKE_ANALYST_ENTITY:-webaccessible_caregiver_analyst}"
FQN="${SNOWFLAKE_ANALYST_FQN:-WEBACCESSIBLE.ANALYST.WEBACCESSIBLE_CAREGIVER_ANALYST}"
SEMANTIC_SCHEMA="${SNOWFLAKE_ANALYST_SEMANTIC_SCHEMA:-WEBACCESSIBLE.ANALYST}"
SEMANTIC_VIEW_NAME="${SNOWFLAKE_ANALYST_SEMANTIC_VIEW:-CAREGIVER_REPORTING}"
ANALYST_ROLE="${SNOWFLAKE_ANALYST_ROLE:-WEBACCESSIBLE_APP_ROLE}"

PROTECTED_FQN="WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER"
SEMANTIC_YAML="$ANALYST_DIR/semantic/caregiver_reporting.yaml"
VALIDATOR="$ANALYST_DIR/validate/validate_semantic_model.py"
VIEWS_SQL="$ANALYST_DIR/migrations/011_analyst_reporting_views.sql"

for command in snow python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf '%s is required.\n' "$command" >&2
    exit 127
  fi
done

FQN_UPPER="$(printf '%s' "$FQN" | tr '[:lower:]' '[:upper:]')"
if [[ "$FQN_UPPER" == "$PROTECTED_FQN" ]]; then
  printf 'Refusing to run: the target entity resolves to the already-live primary caregiver app %s.\n' \
    "$PROTECTED_FQN" >&2
  exit 2
fi

if [[ ! -f "$ANALYST_DIR/snowflake.yml" ]]; then
  printf 'Missing project definition: %s\n' "$ANALYST_DIR/snowflake.yml" >&2
  exit 1
fi

for required in "$SEMANTIC_YAML" "$VALIDATOR" "$VIEWS_SQL"; do
  if [[ ! -f "$required" ]]; then
    printf 'Missing required file: %s\n' "${required#"$ROOT_DIR"/}" >&2
    exit 1
  fi
done

printf '== 1/6 Static semantic model validation ==\n'
python3 "$VALIDATOR" "$SEMANTIC_YAML" "$VIEWS_SQL"

printf '== 2/6 Analyst schema and stage ==\n'
migrations=(
  "$ANALYST_DIR/migrations/010_analyst_schema.sql"
  "$ANALYST_DIR/migrations/011_analyst_reporting_views.sql"
)
for migration in "${migrations[@]}"; do
  if [[ ! -f "$migration" ]]; then
    printf 'Missing migration: %s\n' "${migration#"$ROOT_DIR"/}" >&2
    exit 1
  fi
done

printf 'Applying %s\n' "${migrations[0]#"$ROOT_DIR"/}"
snow sql \
  --connection "$CONNECTION" \
  --filename "${migrations[0]}" \
  --enhanced-exit-codes

printf '== 3/6 Redacted projection views ==\n'
printf 'Applying %s\n' "${migrations[1]#"$ROOT_DIR"/}"
snow sql \
  --connection "$CONNECTION" \
  --filename "${migrations[1]}" \
  --enhanced-exit-codes

printf '== 4/6 Semantic view from YAML ==\n'
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# The YAML is embedded in a dollar-quoted literal. The validator has already refused any
# specification containing '$$' or a UTF-8 BOM, either of which would corrupt the literal.
render_call() {
  local verify_only="$1"
  local outfile="$2"
  python3 - "$SEMANTIC_YAML" "$SEMANTIC_SCHEMA" "$verify_only" "$outfile" <<'PY'
import sys
from pathlib import Path

yaml_path, schema, verify_only, outfile = sys.argv[1:5]
specification = Path(yaml_path).read_text(encoding="utf-8")
if "$$" in specification:
    raise SystemExit("semantic model contains '$$' and cannot be dollar-quoted")
if specification.startswith("\ufeff"):
    raise SystemExit("semantic model starts with a UTF-8 BOM")
if "'" in schema:
    raise SystemExit("target schema name must not contain a quote")
if not specification.endswith("\n"):
    specification += "\n"

statement = (
    "CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(\n"
    f"    '{schema}',\n"
    "    $$\n"
    f"{specification}"
    "$$,\n"
    f"    {verify_only}\n"
    ");\n"
)
Path(outfile).write_text(statement, encoding="utf-8")
PY
}

render_call TRUE "$WORK_DIR/verify_semantic_view.sql"
printf 'Verifying %s.%s without creating it\n' "$SEMANTIC_SCHEMA" "$SEMANTIC_VIEW_NAME"
if ! snow sql \
  --connection "$CONNECTION" \
  --filename "$WORK_DIR/verify_semantic_view.sql" \
  --enhanced-exit-codes; then
  printf '\nSemantic view verification failed. Snowflake rejected the specification.\n' >&2
  printf 'If the failure names a verified query, remove that entry from the verified_queries\n' >&2
  printf 'block in %s and re-run; verified queries are optional.\n' \
    "${SEMANTIC_YAML#"$ROOT_DIR"/}" >&2
  exit 1
fi

render_call FALSE "$WORK_DIR/create_semantic_view.sql"
printf 'Creating or replacing %s.%s\n' "$SEMANTIC_SCHEMA" "$SEMANTIC_VIEW_NAME"
snow sql \
  --connection "$CONNECTION" \
  --filename "$WORK_DIR/create_semantic_view.sql" \
  --enhanced-exit-codes

printf '== 5/6 Grants ==\n'
if [[ "${ANALYST_APPLY_GRANTS:-0}" == "1" ]]; then
  printf 'Granting Cortex Analyst and read-only access to role %s\n' "$ANALYST_ROLE"
  case "$ANALYST_ROLE" in
    *[!A-Za-z0-9_]*)
      printf 'Refusing to grant: role name %s is not a plain identifier.\n' "$ANALYST_ROLE" >&2
      exit 2
      ;;
  esac
  # 012 references the SQL session variable ANALYST_ROLE. Prepending the SET here keeps the
  # role out of source control without depending on Snowflake CLI template syntax.
  {
    printf "SET ANALYST_ROLE = '%s';\n" "$ANALYST_ROLE"
    cat "$ANALYST_DIR/migrations/012_analyst_grants.sql"
  } >"$WORK_DIR/grants.sql"
  snow sql \
    --connection "$CONNECTION" \
    --filename "$WORK_DIR/grants.sql" \
    --enhanced-exit-codes
else
  printf 'Skipped. Granting SNOWFLAKE.CORTEX_ANALYST_USER normally requires ACCOUNTADMIN,\n'
  printf 'so it is not applied by default. When the deploying role can grant it, run:\n'
  printf '  ANALYST_APPLY_GRANTS=1 SNOWFLAKE_ANALYST_ROLE=%s %s\n' \
    "$ANALYST_ROLE" "./scripts/deploy-cortex-analyst.sh"
fi

printf '== 6/6 Streamlit entity ==\n'
snow streamlit deploy "$ENTITY" \
  --project "$ANALYST_DIR" \
  --connection "$CONNECTION" \
  --replace \
  --prune

if [[ "${OPEN_STREAMLIT:-0}" == "1" ]]; then
  snow streamlit get-url "$FQN" --connection "$CONNECTION" --open
else
  snow streamlit get-url "$FQN" --connection "$CONNECTION"
fi

printf '\nDeployed %s over semantic view %s.%s.\n' "$FQN" "$SEMANTIC_SCHEMA" "$SEMANTIC_VIEW_NAME"
printf 'The primary caregiver app %s was not modified or redeployed.\n' "$PROTECTED_FQN"
