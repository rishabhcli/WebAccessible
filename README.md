# WebAccessible

WebAccessible is a caregiver-paid browser guidance service for older adults who need help staying on-task online without handing over control of every click. It watches for “stuck” moments, gives short one-step guidance, and replays previously recorded routines with a low-cost, high-confidence replay loop.

The goal is not to act for the user. The user remains in control and clicks the real page controls herself.

## Track 2 Service

WebAccessible is a defined B2C caregiver service: Susan pays **$15/month per supported adult** for a private routine library, calm one-step recovery, deterministic replay, completion history, and caregiver escalation. That is $180 ARR per active family, well above Track 2's $10 ARR-per-user threshold.

The first paid-pilot proof is one Susan-like caregiver with a live subscription or prepaid monthly pilot, one completed cold run, one warm replay, and a confirmed reduction in assistance calls. Until that happens, the project must describe the pricing as a clear purchase path, not as existing revenue.

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

## Current architecture

```
WebAccessible remote session UI
        │
        ▼
Browserbase managed Chrome (Browser Session + interactive Live View)
        │  cloud CDP session only; never an autonomous Browserbase Agent run
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

All browsing occurs in a Browserbase managed browser session. The backend may observe, navigate, highlight, and verify through CDP, while Browserbase Live View gives Margaret the remote browser she controls. It must never use autonomous Browserbase Agent actions or click/submit for Margaret.

## Data model highlights

- `SESSION_STEPS` logs each step, outcome, latency, and token/cost metrics.
- EverOS stores:
  - `profile` for user preferences + capability notes
  - `agent_case` raw route recording
  - `agent_skill` reusable distilled route
  - `episode` completion memory
- Cost tracking is measured from observed token usage, with Snowflake usage tables treated as secondary verification.

## Planned build flow

1. Verify the existing Browserbase, EverOS, and Snowflake setup and close each remaining live gate.
2. Browserbase session bridge plus remote Live View, guidance panel, halo, and click observation.
3. Record a first run → Case → Skill.
4. Replay engine with selector matching and verification.
5. Session logging and cost reporting.
6. Minimal Streamlit proof view for the real cold-versus-warm cost curve.
7. Optional product depth: caregiver dashboard, voice, scam shield, and SMS escalation.

## Repository status

This repository currently tracks the canonical spec and docs:

- `webaccessible-spec.md`: full product specification
- `IMPLEMENTATION_PLAN.md`: execution-ready architecture, work packages, contracts, gates, and test plan
- `README.md`: this document
- `AGENTS.md`: contributor operating instructions
- `SPONSORS.md`: sponsor utilization documentation
- `docs/sponsors/`: live implementation and evidence contracts for each sponsor
- `docs/SETUP_STATUS.md`: dated provider configuration and readiness boundaries

## References

- `webaccessible-spec.md` — authoritatively defines behavior, constraints, risks, and demo plan.
- `IMPLEMENTATION_PLAN.md` — defines implementation decisions, sequencing, acceptance gates, and traceability.
- `SPONSORS.md` — outlines how Snowflake, EverOS, and Beta Fund are utilized in implementation and proof.
- `docs/sponsors/BROWSERBASE.md` — defines the managed browser, CDP, Live View, and user-control execution contract.
