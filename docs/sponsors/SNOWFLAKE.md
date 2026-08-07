# Snowflake Implementation Contract

## Role

Snowflake is WebAccessible's system of record for session telemetry, token/cost accounting, fuzzy skill matching, scam classification, weekly summaries, and caregiver reporting. It is not on the interactive guidance hot path; FastAPI keeps guidance responsive and writes its measured result to Snowflake.

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
| `AI_COUNT_TOKENS` | Price a step before/at spend. | Store the calculation inputs and rate-card version. |
| `AI_COMPLETE` | Produce a batch weekly caregiver summary. | Use persisted session data, not unverified browser claims. |
| Cortex Analyst | Answer Susan's questions over real data. | Read-only, authorized queries only. |

### 4. Streamlit caregiver view

The Streamlit in Snowflake view reads persisted data and presents:

- Session timeline and step outcomes.
- Cost-by-run curve with cold/warm replay comparison.
- Completion episode answer such as “The water bill was paid on Aug 6 for $64.20.”
- Escalation state and a read-only session link.
- Weekly summary after the underlying rows exist.

No empty or disconnected view may display plausible sample metrics as live data.

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
