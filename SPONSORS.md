# Sponsors Utilization Guide

This document summarizes how WebAccessible uses each named sponsor in the current build plan.

## 1) Snowflake

**Role in product:** primary data system for telemetry, cost accounting, memory-backed matching, and reporting.

### How Snowflake is used

- Capture every step in `SESSION_STEPS` (`session_id`, `user_id`, `step_no`, `task_name`, `skill_id`, `model_used`, token/cost fields, outcome, timestamps).
- Drive cost proof with `AI_COUNT_TOKENS` and published rate card; write results to product-owned tables for demo stability.
- Use Cortex ML functions for supporting analytics: `AI_EMBED` for skill-fuzzy matching, `AI_CLASSIFY` for Scam Shield triage, and `AI_COMPLETE` for weekly summaries.
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
- Use search/read APIs to resolve routine requests and hydrate prompt context.
- Accept user-uploaded documents/facts (for example paper bill image/PDF) via upload path.

### Why this matters

EverOS is the mechanism that makes replay cheap and reliable, turning first-run cost into low-cost recurring support.

## 3) Beta Fund

**Role in product:** program sponsorship context for delivery (timeline, pitch format, and audience framing).

### How Beta Fund support is represented

- Credit Beta Fund explicitly in project framing and demo materials.
- Keep build/deploy plan aligned with submission timing and visible proof expectations.
- Ensure deliverables reflect the event context, including concise sponsor-focused narrative.

## Cross-sponsor execution principles

- No sponsor claim is presented unless backed by behavior in the live backend path.
- No sponsor dependency should be faked by local-only fixtures for demo narratives.
- For each sponsor usage path, preserve a fail-safe path and clear boundary conditions in docs.

## Quick sponsor proof checklist

- [ ] Session telemetry is persisted and queryable in Snowflake.
- [ ] Cold run and replay run cost differences are computed from real session rows.
- [ ] Skill creation uses the EverOS case/flush flow.
- [ ] Sponsor mentions in demos include what each brings to the build, not generic praise.

