# Cortex Analyst caregiver reporting

An isolated Streamlit in Snowflake application that answers plain-English caregiver
questions over verified WebAccessible data using Cortex Analyst.

This is a second, independent application. It does not modify, redeploy, or share a stage
with the already-live `WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER` entity.

## Deploy command

```bash
SNOWFLAKE_CONNECTION=webaccessible ./scripts/deploy-cortex-analyst.sh
```

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `SNOWFLAKE_CONNECTION` | `webaccessible` | Snowflake CLI connection name. |
| `ANALYST_APPLY_GRANTS` | `0` | Set to `1` to apply `012_analyst_grants.sql`. Granting `SNOWFLAKE.CORTEX_ANALYST_USER` normally requires ACCOUNTADMIN, so it is off by default. |
| `SNOWFLAKE_ANALYST_ROLE` | `WEBACCESSIBLE_APP_ROLE` | Role that owns the Streamlit entity and therefore needs Cortex Analyst access. |
| `OPEN_STREAMLIT` | `0` | Set to `1` to open the deployed app in a browser. |

Static validation alone, with no Snowflake connection:

```bash
python3 snowflake/analyst/validate/validate_semantic_model.py
```

## What gets created

| Object | Type |
|---|---|
| `WEBACCESSIBLE.ANALYST` | Schema |
| `WEBACCESSIBLE.ANALYST.WEBACCESSIBLE_ANALYST_STAGE` | Stage, separate from `WEBACCESSIBLE_STREAMLIT_STAGE` |
| `WEBACCESSIBLE.ANALYST.V_CAREGIVER_SESSION` | View |
| `WEBACCESSIBLE.ANALYST.V_CAREGIVER_ASSISTANCE_EVENT` | View |
| `WEBACCESSIBLE.ANALYST.V_CAREGIVER_MODEL_USAGE` | View |
| `WEBACCESSIBLE.ANALYST.V_CAREGIVER_REPLAY_EVIDENCE` | View |
| `WEBACCESSIBLE.ANALYST.V_CAREGIVER_PROVIDER_SYNC` | View |
| `WEBACCESSIBLE.ANALYST.V_CAREGIVER_ESCALATION` | View |
| `WEBACCESSIBLE.ANALYST.CAREGIVER_REPORTING` | Semantic view |
| `WEBACCESSIBLE.ANALYST.WEBACCESSIBLE_CAREGIVER_ANALYST` | Streamlit |

Nothing in `WEBACCESSIBLE.APP` is created, altered, or dropped.

## Architecture

```text
WEBACCESSIBLE.APP verified views        (product-owned, unchanged)
  V_COLD_WARM_COST_CURVE  V_SESSION_TIMELINE  V_MODEL_COST_LINEAGE
  V_SELECTOR_REPLAY_EVIDENCE  V_PROVIDER_SYNC_STATUS  V_ESCALATION_OVERVIEW
        |
        |  column allowlist + verified-row filter  (011_analyst_reporting_views.sql)
        v
WEBACCESSIBLE.ANALYST.V_CAREGIVER_*     (redacted projection layer)
        |
        |  semantic/caregiver_reporting.yaml
        |  SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML
        v
WEBACCESSIBLE.ANALYST.CAREGIVER_REPORTING   (semantic view)
        |
        |  POST /api/v2/cortex/analyst/message  {"semantic_view": ...}
        v
WEBACCESSIBLE.ANALYST.WEBACCESSIBLE_CAREGIVER_ANALYST   (Streamlit)
```

Semantic views are Snowflake's recommended Cortex Analyst input; stage-hosted semantic model
YAML files remain supported only for backward compatibility. The YAML here is the single
authored source: it is statically validated locally, verified server-side with
`verify_only=TRUE`, and only then compiled into the semantic view.

## Exposed subject areas

| Logical table | Grain | Covers |
|---|---|---|
| `sessions` | one verified run | outcomes, cold/warm/repair class, run ordering, verified cost status, skill and provider identifiers |
| `assistance_events` | one step | step outcomes (`ok`, `wrong_click`, `stuck`, `escalated`), guidance mode, replay rate, site domain |
| `model_usage` | one model call | actual provider token classes, rate-card lineage, verified USD cost |
| `replay_evidence` | one selector attempt | zero-model warm-replay invariant, selector match and verification rates |
| `provider_sync` | one verified run | Browserbase lifecycle, EverOS memory state, telemetry completeness |
| `escalations` | one escalation | reason, delivery lifecycle, caregiver response |

All five non-hub tables join to `sessions` on `run_id`, so the model is a single-hub star with
no circular or ambiguous join path.

## Boundaries this application enforces

**Verified data only.** Every projection view reads a product-owned verified view and filters
on `is_verified`, `run_is_verified`, or an inner join to `V_VERIFIED_SESSION_RUNS`. Fixture
rows and non demo/production rows are already excluded upstream.

**Excluded columns.** Raw DOM text, prompts, uploaded documents, phone numbers, account
numbers, credentials, and full URLs are absent from the upstream product tables by
construction. On top of that, the projection layer drops `verification_predicate` (may embed
expected page text), `selector_fingerprint` (may encode DOM attribute values), the provider
correlation hashes, and `caregiver_response_metadata`. Only the origin host is exposed, as
`site_domain`. `validate_semantic_model.py` fails if any of these names reappear in an
`expr`.

**Cost.** `MODEL_COSTS.amount_usd` is never exposed directly. The only cost columns are
`verified_cost_usd` and `actual_cost_usd`, which are `NULL` unless the call has actual
provider usage, a calculated `MODEL_COSTS` row, and a matching `COST_RATE_CARDS` row.
`unpriced_model_call_count` and `cost_unavailable_session_count` accompany every cost answer,
so an incomplete total is always labelled instead of quietly under-reported. No price is
inferred, carried across models, or read from `ACCOUNT_USAGE`.

**Usage.** `SESSION_STEPS` records zeros for observed events, so `assistance_events`
deliberately carries no token or latency columns. Model usage and latency come only from
`model_usage`.

**Citation.** The semantic view's SQL-generation instructions require `run_id`, `session_id`,
and a timestamp in every result. Because that depends on the model complying, the app also
runs its own parameterized evidence query for the answered scope and always renders the
contributing run IDs, session IDs, and UTC timestamps, plus the Cortex Analyst `request_id`
and the generated SQL.

**Scope.** Participant names are not stored in Snowflake; `docs/privacy-data-map.md` keeps
them in EverOS only. A question such as "How did Margaret do this week?" is therefore scoped
by the `user_id` selected in the sidebar, and the app says so on screen rather than guessing a
name-to-identifier mapping. Generated SQL that does not carry the selected `user_id` is
refused instead of executed.

**Read-only.** Generated SQL must be a single statement beginning with `SELECT` or `WITH`,
with no DDL or DML keyword, or it is not executed.

**Empty data.** An empty scope, an empty result, a refused statement, a failed statement, or
an Analyst response with no query all render the exact words `No verified data`. No sample,
example, or typical metric is ever produced.

## Verification performed

Static only, as required. No tests were run, no live Snowflake object was created or altered,
and nothing was committed or pushed.

- `python3 validate/validate_semantic_model.py` passes: key vocabulary, globally unique
  semantic expression names, aggregate-only non-derived metrics, single-hub relationships,
  required custom instructions, and every `expr` cross-checked against the columns actually
  projected by `011_analyst_reporting_views.sql`.
- `python3 -m compileall` and `ruff check` pass for the app and the validator.
- `bash -n` passes for the deployment script.
- The semantic view has not been compiled by Snowflake. Step 4 of the deployment script does
  that with `verify_only=TRUE` before creating anything. If Snowflake rejects a
  `verified_queries` entry, delete that entry and re-run; verified queries are optional.
