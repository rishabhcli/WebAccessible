# WebAccessible

WebAccessible is a Chrome-side browser assistant for people who need help staying on-task online without handing over control of every click. It watches for “stuck” moments, gives short one-step guidance in a side panel, and replays previously recorded routines with a low-cost, high-confidence replay loop.

The goal is not to act for the user. The user remains in control and clicks the real page controls herself.

## Why this exists

Older adults can understand recurring workflows but often get confused at exactly the same points. WebAccessible:

- Detects stalled behavior from interaction signals.
- Gives calm, one-line guidance instead of large autonomous actions.
- Learns repeatable routines into reusable skills.
- Distinguishes “cold runs” from replayed routines so cost and behavior are predictable.
- Escalates uncertainty or money-sensitive moments to a caregiver contact.

## Core behavior

- Ambient help is triggered by inactivity patterns, repeated visits, unproductive scrolling, and explicit help requests.
- Guidance is one step at a time:
  1. Surface clear instruction text.
  2. Highlight the target control.
  3. Let the user click.
  4. Verify page change and move to the next step.
- Irreversible actions (payments, sensitive identity entry, deletes) always require explicit user confirmation.
- Skills repair themselves on minor UI drift via a focused single-step selector strategy.
- Scam-style cues (phishing, fake urgency, unfamiliar identity-data pages) generate a pause-and-escalate intervention.

## Architecture (as defined in the spec)

```
Chrome extension (MV3)
├─ content script — halo overlay, click capture, DOM snapshot
└─ side panel — one instruction, large type, optional voice
        │  localhost:8000
        ▼
Python backend (FastAPI)
├─ stuck detector     (rules, no model)
├─ guidance engine    (fast model, cold runs)
├─ replay engine      (selector match + verify, no model)
├─ EverOS client      (search/add/flush/get/upload)
└─ Snowflake writer   (SESSION_STEPS telemetry)
        │
        ▼
Streamlit in Snowflake — caregiver view, cost curve, weekly summaries
```

## Data model highlights

- `SESSION_STEPS` logs each step, outcome, latency, and token/cost metrics.
- EverOS stores:
  - `profile` for user preferences/preferences + capability notes
  - `agent_case` raw route recording
  - `agent_skill` reusable distilled route
  - `episode` completion memory
- Cost tracking is measured from observed token usage, with Snowflake usage tables treated as secondary verification.

## Planned build flow

1. Snowflake + EverOS key setup and schema.
2. Extension shell (side panel + halo overlay + click capture).
3. Record a first run → Case → Skill.
4. Replay engine with selector matching and verification.
5. Session logging and cost reporting.
6. Optional polish: dashboard charting, voice, scam shield, SMS escalation.

## Repository status

This repository currently tracks the canonical spec and docs:

- `webaccessible-spec.md`: full product specification
- `README.md`: this document
- `AGENTS.md`: contributor operating instructions
- `SPONSORS.md`: sponsor utilization documentation

## References

- `webaccessible-spec.md` — authoritatively defines behavior, constraints, risks, and demo plan.
- `SPONSORS.md` — outlines how Snowflake, EverOS, and Beta Fund are utilized in implementation and proof.
