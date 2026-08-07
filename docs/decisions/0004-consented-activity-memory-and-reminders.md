# 0004: Consented activity memory and routine reminders

## Status

Accepted on August 7, 2026.

## Decision

WebAccessible records sanitized managed-session activity only after explicit participant permission.
Each accepted event contributes task, origin, event kind, outcome, and local timing context; sensitive
values, paths, queries, raw DOM, and page content remain excluded. Operational SQLite keeps the
idempotent observation/index state, while a session-level understanding is written to EverOS as the
durable episode and optional foresight context.

Daily, weekly, and monthly patterns are inferred deterministically after two or more task starts.
Proactive reminders require a second permission, appear only inside the routine chooser, explain their
basis, and can be snoozed. Accepting a reminder creates the ordinary saved-routine session and opens
its allowlisted start URL. It does not grant authority to click, type, submit, accept permissions, or
cross an irreversible boundary.

## Consequences

- The product can build context about what happened and when a routine is usually started.
- A reminder can continue into guidance with one explicit participant action.
- Reminder delivery cannot be confused with stuck detection or autonomous browser execution.
- Revoking activity-memory permission necessarily disables reminder inference and presentation.
