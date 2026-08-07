# Snowflake Implementation Contract

## Role

Snowflake is WebAccessible's system of record for session telemetry, token/cost accounting, and caregiver reporting. Snowflake Cortex `AI_COMPLETE` is also the live model path for bounded cold-run and selector-repair guidance; deterministic replay does not invoke a model. FastAPI validates every structured Cortex result into the application `GuidanceDecision` contract before it can be presented.

## Live paths to implement

### 1. `SESSION_STEPS` telemetry

The backend writes one row for every observed, guided, replayed, wrong-click, stuck, or escalated step. The required columns come from the product spec:

```sql
CREATE TABLE SESSION_STEPS (
  session_id STRING, user_id STRING, step_no INT,
  task_name STRING, skill_id STRING,
  url_domain STRING, action STRING,
  model_used STRING, input_tokens INT, output_tokens INT,
  credits NUMBER(18,9), replayed_from_memory BOOLEAN,
  latency_ms INT, outcome STRING, ts TIMESTAMP_NTZ
);
```

`outcome` is one of `ok`, `wrong_click`, `stuck`, or `escalated`. The service rejects a telemetry write that lacks session identity, step number, replay state, outcome, or timestamp.

### 2. Product-owned cost proof

For each model call, FastAPI records actual input/output token measurements, invokes `AI_COUNT_TOKENS` where applicable, attaches a versioned published rate card, and persists the resulting credits/USD amount in product-owned data.

The cost curve groups real task sessions in chronological order, making the genuine cold run the baseline and later replay runs the comparison. `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AISQL_USAGE_HISTORY` is reconciliation/backfill only; it must never be the live demo source because it can lag for hours.

### 3. Cortex feature boundaries

| Cortex feature | Product job | Guardrail |
|---|---|---|
| `AI_EMBED` and similarity | Match a fuzzy routine request to an existing skill. | Do not make an irreversible decision from similarity alone. |
| `AI_CLASSIFY` | Triage page risk as `legitimate`, `phishing`, `fake_support`, or `unknown_payment`. | High-risk or unknown sensitive pages pause and escalate; classification does not click or dismiss the page. |
| `AI_COUNT_TOKENS` | Estimate input size before a guidance call. | Treat it as an estimate only; actual cost uses `AI_COMPLETE` usage and the effective rate card. |
| `AI_COMPLETE` | Produce one bounded cold/repair guidance step as structured output. | Validate the full contract, require a submitted candidate ID, and never perform the action. |
| Cortex Analyst | Answer Susan's questions over real data. | Read-only, authorized queries only. |

### 4. Streamlit caregiver view

The Streamlit in Snowflake view reads persisted data and presents:

- Session timeline and step outcomes.
- Cost-by-run curve with cold/warm replay comparison.
- Completion episode answer such as “The water bill was paid on Aug 6 for $64.20.”
- Escalation state and a read-only session link.
- Weekly summary after the underlying rows exist.

No empty or disconnected view may display plausible sample metrics as live data.

## Live provider qualification - 2026-08-07

The scoped service role completed the following sanitized live operations:

- `AI_COUNT_TOKENS` query `01c63c53-0107-59eb-000f-e9160001b1aa` estimated 304 input tokens for the exact bounded prompt and provider schema.
- `AI_COMPLETE` query `01c63c53-0107-500e-0000-000fe91661a9` returned model `claude-haiku-4-5`, 1,506 actual prompt tokens, 230 completion tokens, and 1,736 total tokens.
- The result selected the submitted `Lettuce` checkbox candidate and returned a valid `aria_state_equals` predicate using role `checkbox`, accessible name `Lettuce`, state `checked`, and expected value `true`.
- Rate-card migration query `01c63c4f-0107-5622-000f-e9160001002e` inserted the input and output rows for `snowflake-cortex-any-region-2026-08-07`; readback query `01c63c4f-0107-59eb-000f-e9160001b1a6` returned both rows.
- `SHOW TABLES` query `01c63c54-0107-59ea-000f-e9160001ee66` and `SHOW VIEWS` query `01c63c54-0107-59eb-000f-e9160001b1ae` confirmed all product tables and evidence views. `SHOW STREAMLITS` query `01c63c54-0107-59ea-000f-e9160001ee6a` confirmed `WEBACCESSIBLE_CAREGIVER` exists in `WEBACCESSIBLE.APP`.

The authoritative [Snowflake Service Consumption Table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf), Table 6(a), is effective August 7, 2026 and prices `claude-haiku-4-5` at 0.60 AI Credits per million input tokens and 3.00 AI Credits per million output tokens. The account parameter query `01c63c4c-0107-5622-000f-e91600010022` returned `ANY_REGION`; Snowflake's [Cortex pricing documentation](https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing) sets that routing mode at $2.00 per AI Credit.

This is provider and schema qualification, not an end-to-end participant-run claim. No cold/warm task pair or matching persisted `MODEL_CALLS`/`MODEL_COSTS` drill-through was created by this probe, and Streamlit entity existence is not browser-render proof.

## Evidence required before demo claim

- A query shows backend-created `SESSION_STEPS` rows for both the cold and warm runs.
- The cost curve can be traced from screen to product-owned rows, token counts, and rate-card version.
- The Streamlit view displays the actual demo session.
- A captured readiness check shows failed Snowflake access as unavailable, never as a fabricated success.

## Failure behavior

- If Snowflake is unavailable in demo/production mode, surface degraded persistence explicitly and block the sponsor cost-proof claim.
- Do not silently retain unsynced telemetry as if it were confirmed in Snowflake. Queueing may be implemented later, but its state must be visible and reconciled idempotently.
- Never replace the cost curve with local fixtures, estimates, or lagging account-usage rows.

## Source traceability

- [SPONSORS.md](../../SPONSORS.md), Snowflake section and sponsor proof checklist.
- [webaccessible-spec.md](../../webaccessible-spec.md), sections 4 and 5.
- [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md), phases 0 and 5.
