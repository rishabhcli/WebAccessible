# ADR 0001: Hosted Session Runtime

## Status

Accepted on 2026-08-07.

## Decision

Ship the React production bundle and FastAPI service together on one HTTPS Fly application. A single persistent process owns active CDP connections and SSE streams, while a Fly volume retains only operational state and the Snowflake outbox.

Browserbase Browser Sessions remain the sole browser runtime. EverOS is the authoritative profile, fact, Case, Skill, and Episode memory. Snowflake is the telemetry, cost-lineage, and reporting system of record.

## Consequences

- Provider keys and CDP URLs stay server-side.
- The browser and API share one origin in production.
- Browserbase sessions are explicitly terminated on every terminal application state.
- Operational SQLite is not presented as product memory or sponsor evidence.
