# AGENTS.md

## Purpose

This repository documents and builds the WebAccessible product direction. Use this file as the default operating guide for future implementation work.

## Scope

Primary source of truth is:

- `webaccessible-spec.md` (behavioral spec, architecture, and demo commitments)

Current execution-provider addendum:

- `docs/sponsors/BROWSERBASE.md` supersedes the spec's local MV3/localhost topology. Browserbase Browser Sessions, CDP, and interactive Live View are the only production/demo browser path; autonomous Browserbase Agent actions are prohibited.

Execution source:

- `IMPLEMENTATION_PLAN.md` (component contracts, implementation order, gates, and verification)

Supporting docs:

- `README.md` (project summary and contributor handoff)
- `SPONSORS.md` and `docs/sponsors/` (live integration claims and evidence requirements)

## Design and product constraints

- Do not design WebAccessible as a fully autonomous browser agent.
- The user must always perform the actual click/submit actions.
- “Before irreversible actions” means the tool must pause and surface a clear confirmation path.
- Cold-run guidance can use models; replay must stay deterministic and selector-first.
- Never store or handle user passwords.

## Interaction model

- Detect “stuck” from observable interaction signals, not proactive prompts.
- Guidance content is one sentence, then next-step verification.
- Never flood the user with repeated popups; apply cooldown on dismissed help.
- Escalate ambiguity/money-risk situations (including repeated failures) to Susan workflow.

## Data and safety constraints

- Keep session telemetry, skill logs, and cost metrics consistent with Snowflake `SESSION_STEPS`.
- Cost accounting should rely on actual token measurements.
- Treat Snowflake `ACCOUNT_USAGE` billing views as secondary/backfill only.
- Scam warnings and unusual money/data requests should produce non-blocking, calm intervention with caregiver notification.

## Development habits (required)

- Preserve the spec-first workflow: make code changes from explicit spec bullets and table definitions.
- Keep implementation choices local to the repo and traceable to architecture sections in the spec.
- Prioritize minimal, reversible changes with clear failure boundaries.
- If implementation is incomplete, annotate missing parts explicitly rather than simulating behavior.
- Prefer explicit tests and end-to-end manual checks for:
  - stuck detection to help prompt
  - one-step guidance flow
  - skill replay selector matching
  - escalation path

## Collaboration norms

- Make README/AGENTS updates when architecture or constraints change.
- If a behavior conflict appears, prefer security, clarity, and user-control constraints over optimization.
