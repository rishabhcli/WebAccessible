#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONNECTION="${SNOWFLAKE_CONNECTION:-webaccessible}"
ENTITY="${SNOWFLAKE_STREAMLIT_ENTITY:-webaccessible_caregiver}"
FQN="${SNOWFLAKE_STREAMLIT_FQN:-WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER}"

if ! command -v snow >/dev/null 2>&1; then
  printf 'Snowflake CLI (snow) is required.\n' >&2
  exit 127
fi

snow streamlit deploy "$ENTITY" \
  --project "$ROOT_DIR/snowflake" \
  --connection "$CONNECTION" \
  --replace \
  --prune

if [[ "${OPEN_STREAMLIT:-0}" == "1" ]]; then
  snow streamlit get-url "$FQN" --connection "$CONNECTION" --open
else
  snow streamlit get-url "$FQN" --connection "$CONNECTION"
fi
