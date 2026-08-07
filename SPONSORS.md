# Sponsors Utilization Guide

This document summarizes how WebAccessible uses each named sponsor in the current build plan, plus the required Browserbase execution provider.

## 1) Snowflake

**Role in product:** primary data system for telemetry, cost accounting, memory-backed matching, and reporting.

### How Snowflake is used

- Capture every step in `SESSION_STEPS` (`session_id`, `user_id`, `step_no`, `task_name`, `skill_id`, `model_used`, token/cost fields, outcome, timestamps).
- Drive cost proof with `AI_COUNT_TOKENS` and published rate card; write results to product-owned tables for demo stability.
- Use Cortex ML functions in the live path:
  - `AI_COMPLETE` for next-action planning (`services/autopilot.py`) and for phrasing
    grounded recall answers (`services/recall.py`),
  - `AI_COUNT_TOKENS` measured in the *same statement* as the completion, so cost proof
    reflects the exact billed prompt at one round trip,
  - `AI_EMBED` + `VECTOR_COSINE_SIMILARITY` for routine phrase matching when a
    participant's words share no term with the routine name (`services/orchestrator.py`),
  - `AI_CLASSIFY` for Scam Shield triage on the unfamiliar-page pause path
    (`services/scam_shield.py`).
- Connections are pooled: a Snowflake login is no longer paid per query.
- Serve family/caregiver views in Streamlit in Snowflake using SQL against persisted session data.

### Why this matters

Snowflake is the sponsor-backed system-of-record and the source of the measurable business proof:

- warm replay runtime and cold-run cost comparison by run number,
- per-session confusion/escalation rates,
- cross-site hardness dataset for older adults.

### Evidence to keep current in demos

- `SESSION_STEPS` rows must be populated by the backend.
- `ACCOUNT_USAGE` is **supplemental only** (lagging views are not used as live source-of-truth).
- Cost curve should be computed from internal totals and shown to Susan/owner views.

## 2) EverMind / EverOS

**Role in product:** persistent user/task memory that enables replay and caregiver-readable procedures.

### How EverOS is used

- Store and retrieve memory types:
  - `profile` (reading size, voice preference, capability notes),
  - `atomic_fact` (fuzzy aliasing like "light bill"),
  - `agent_case` (raw recorded run),
  - `agent_skill` (distilled replayable routine),
  - `episode` (completion memory and proof events),
  - `foresight` (timing nudges).
- During cold run completion, flush trajectory to generate `agent_case` → `agent_skill`.
- Write `foresight` memory whenever a recurring timing pattern is inferred, so the
  proactive nudge substrate lives in EverOS and not only in local state.
- Mine `atomic_fact` vocabulary so a participant's own words ("the light bill") resolve to
  the distilled routine name.
- Use search/read APIs to resolve routine requests and hydrate prompt context. The SDK
  client is long-lived, so memory reads reuse a warm connection pool.
- Accept user-uploaded documents/facts (for example paper bill image/PDF) via upload path.

### Why this matters

EverOS is the mechanism that makes replay cheap and reliable, turning first-run cost into low-cost recurring support.

## 3) Beta Fund

**Role in product:** program sponsorship context for delivery (timeline, pitch format, and audience framing).

### How Beta Fund support is represented

- Credit Beta Fund explicitly in project framing and demo materials.
- Keep build/deploy plan aligned with submission timing and visible proof expectations.
- Ensure deliverables reflect the event context, including concise sponsor-focused narrative.

## 4) Browserbase

**Role in product:** the only managed browser environment in which WebAccessible browses target sites.

### How Browserbase is used

- Create and retain a managed Browserbase Browser Session for each active task.
- Drive the session through CDP for navigation, sanitized DOM/accessibility observation, verified highlighting, and page-state checks.
- Embed Browserbase Live View so Margaret performs every page click, text entry, submit, and irreversible confirmation herself.
- Stop each Browserbase session explicitly when the task ends.

### How Browserbase is driven

- WebAccessible drives the managed session itself over CDP: navigation, sanitized DOM and
  accessibility observation, and the click/type/select actions that complete the task.
- Browserbase's own autonomous Agent surface is still not used. The planning loop, the
  action allowlist, and the safety pauses are WebAccessible's, so the boundaries below are
  enforced in this codebase rather than delegated to a provider feature.
- Live View is embedded so the participant watches the real page and can take over at any
  pause without losing the session.

### Non-negotiable boundary

- Money, identity, and deletion steps pause the run for a participant decision.
- Passwords are never read or typed by the agent.
- No local Chromium, extension-controlled local browser, or fixture may substitute for the Browserbase path in a production or demo claim.
- Browserbase free-plan/session limits must be surfaced as a blocked provider state rather than replaced with a local run.

## Cross-sponsor execution principles

- No sponsor claim is presented unless backed by behavior in the live backend path.
- No sponsor dependency should be faked by local-only fixtures for demo narratives.
- For each sponsor usage path, preserve a fail-safe path and clear boundary conditions in docs.

## Quick sponsor proof checklist

- [ ] Session telemetry is persisted and queryable in Snowflake.
- [ ] Cold run and replay run cost differences are computed from real session rows.
- [ ] Skill creation uses the EverOS case/flush flow.
- [ ] Sponsor mentions in demos include what each brings to the build, not generic praise.
- [ ] Browserbase session and Live View evidence shows that the cold and warm runs occurred in a managed cloud browser, with explicit stop evidence.
