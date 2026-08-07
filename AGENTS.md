# AGENTS.md

## Purpose

This repository documents and builds the WebAccessible product direction. Use this file as the default operating guide for future implementation work.

## Scope

Primary source of truth is:

- `webaccessible-spec.md` (behavioral spec, architecture, and demo commitments)

Current execution-provider addendum:

- `docs/sponsors/BROWSERBASE.md` supersedes the spec's local MV3/localhost topology. Browserbase Browser Sessions, CDP, and interactive Live View are the only production/demo browser path; autonomous Browserbase Agent actions are prohibited.
- Development may use the explicit local Playwright Chromium adapter and deterministic planner
  for provider-independent browser QA. This mode is local evidence only and must never be
  enabled or described as provider evidence in demo or production.

Execution source:

- `IMPLEMENTATION_PLAN.md` (component contracts, implementation order, gates, and verification)

Supporting docs:

- `README.md` (project summary and contributor handoff)
- `SPONSORS.md` and `docs/sponsors/` (live integration claims and evidence requirements)

## Design and product constraints

**Execution model changed on 2026-08-07.** WebAccessible now performs the task itself. The
earlier constraint — that the participant must perform every click and submit — has been
retired by product decision. Treat the rules below as current and the guided-only language
in `webaccessible-spec.md` §Phase 1–6 as superseded where the two disagree.

- The agent drives the managed browser: clicking, typing, selecting, and navigating.
- The dashboard reports what the agent *did*; it does not instruct the participant to act.
- Three boundaries survive autonomy and must not be removed:
  - **Money, identity, and deletion pause the run** and ask the participant to decide.
    Reversible steps — adding to a cart, joining a queue, holding an appointment — proceed.
  - **Passwords are never read or typed.** The run stops and says so.
  - **Leaving the origin the run started on pauses** for confirmation.
- Cold-run planning can use models; replay must stay deterministic and selector-first.
- An action may only target an element from the same sanitized snapshot the planner saw.

## Interaction model

- Entry is passwordless. There is no participant login and no caregiver access code; the
  caregiver console opens directly against activity from the same device.
- An explicit participant opt-in enables routine reminders learned from their own task
  timing. Reminders are pushed on the participant stream, not polled from one screen.
- A reminder is a dismissible suggestion. Accepting it is the permission boundary that
  lets a run start; a lapsed routine is phrased as a lapse and expires rather than nagging.
- Step narration is one short plain sentence per action, written for the participant —
  never selectors, IDs, or DOM language.
- Escalate ambiguity/money-risk situations (including repeated failures) to Susan workflow.

## Curated demos

`backend/app/domain/demos.py` holds the three offered tasks (DMV queue, Whole Foods cart,
haircut booking) and the origin allowlist. Free-form prompts are fully supported; the
allowlist only bounds unprompted origin changes mid-run.

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
