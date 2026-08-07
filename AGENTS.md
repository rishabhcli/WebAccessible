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
- Two boundaries survive autonomy:
  - **Money and deletion pause the run** and ask the participant to decide. Reversible
    steps — adding to a cart, joining a queue, holding an appointment — proceed.
  - **Passwords are never read or typed.** The run stops and says so.
- There is **no origin allowlist**; a run follows the task to any host. Real errands cross
  hosts constantly (the DMV hands its queue to Qmatic), and pausing at each handoff made
  the product unusable.
- Identity classification pauses a free-form run but not a curated demo, whose details are
  invented. A planner labels a plain click on "Renew your driver's license" as identity
  purely from the words in it, which stopped demo runs on their first step.
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

`backend/app/domain/demos.py` holds the three offered tasks (DMV queue, Instacart Sprouts
cart, haircut booking). Free-form prompts are equally supported.

Demos require `ACTION_PLANNER_PROVIDER=snowflake_cortex`. The deterministic
`LocalActionPlanner` is a development fallback that cannot navigate a real multi-step
site — on the live DMV it spent every step re-clicking the page's own search box — and
`config.py` already rejects it for demo and production.

A demo is one tap: it fills and submits without asking the participant anything. Form
values come from the fictional persona in `backend/app/domain/persona.py` — an RFC 2606
mailbox and a 555-01xx phone number, so no real person's details are ever typed. A
free-form run has no persona and fills only what the participant's prompt contained.

A button labelled "Submit" is not a risk in itself and must not be treated as one; it is
how service selections, searches, and date pickers advance. Money, identity, deletion,
and passwords remain the boundaries that stop a run.

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
