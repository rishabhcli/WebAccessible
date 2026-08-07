#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONNECTION="${SNOWFLAKE_CONNECTION:-webaccessible}"

if ! command -v snow >/dev/null 2>&1; then
  printf 'Snowflake CLI (snow) is required.\n' >&2
  exit 127
fi

migrations=(
  "$ROOT_DIR/snowflake/migrations/001_session_steps.sql"
  "$ROOT_DIR/snowflake/migrations/002_product_tables.sql"
  "$ROOT_DIR/snowflake/migrations/003_evidence_views.sql"
  "$ROOT_DIR/snowflake/migrations/004_cortex_rate_cards.sql"
)

for migration in "${migrations[@]}"; do
  if [[ ! -f "$migration" ]]; then
    printf 'Missing migration: %s\n' "$migration" >&2
    exit 1
  fi

  printf 'Applying %s\n' "${migration#"$ROOT_DIR"/}"
  snow sql \
    --connection "$CONNECTION" \
    --filename "$migration" \
    --enhanced-exit-codes
done

printf 'Snowflake migrations applied through 004_cortex_rate_cards.sql.\n'
