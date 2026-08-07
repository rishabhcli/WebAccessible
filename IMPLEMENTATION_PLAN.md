# WebAccessible Implementation Plan

## Purpose and delivery boundary

Build the smallest live, sponsor-backed WebAccessible path that proves the product thesis:

1. Margaret completes one real browser task while retaining every click and submit action.
2. The successful teach run becomes a readable EverOS skill.
3. The same task replays deterministically with no model when selectors match.
4. Snowflake records both runs and renders the real cold-versus-warm cost curve.

This plan implements the architecture in [webaccessible-spec.md](webaccessible-spec.md), sections 2-5, and the sponsor evidence rules in [SPONSORS.md](SPONSORS.md). It is intentionally not a plan for an autonomous browser agent. The extension never stores passwords, authenticates, clicks, submits, closes tabs, or completes an irreversible action for the user.

## Scope and priorities

### Required demo spine

- MV3 Chrome extension with a side panel, page halo, click capture, and DOM snapshots.
- FastAPI service for deterministic stuck detection, cold-run guidance, route recording, deterministic replay, EverOS integration, and Snowflake telemetry.
- EverOS Case-to-Skill flow, including a readable Markdown skill and a stored completion episode.
- Snowflake `SESSION_STEPS` persistence, product-owned token/cost calculation, and a Streamlit cost curve from real session rows.
- A rehearsed live target task with no login wall during the demo, plus a backup recording of the same genuine flow.

### Deferred only after the demo spine works

Implement in this order: caregiver dashboard, SMS delivery, scam shield, voice output, cross-user site-friction index. Keep the deterministic answer to “Did I already pay it?” in the core scope because it is low-cost and demonstrates memory value.

## Proposed repository layout

Create these top-level application areas. Names are intentionally descriptive and can be adjusted to match the selected package tooling before scaffolding.

```text
extension/                    # Chrome MV3 TypeScript extension
  src/background/
  src/content/
  src/sidepanel/
  src/shared/
backend/                      # Python FastAPI service
  app/api/
  app/domain/
  app/services/
  app/integrations/
  tests/
snowflake/
  sql/                         # schema, views, Cortex queries
  streamlit/                   # caregiver and proof views
docs/
  demo-runbook.md
  sponsor-evidence.md
```

Keep browser-facing code separate from provider clients. The extension owns observation and presentation; the backend owns decisions, routing state, safety policy, persistence, and provider calls.

## Architecture and contracts

### Extension to backend

Use a versioned localhost HTTP/WebSocket contract between the extension and `http://localhost:8000`. Every event includes `session_id`, `user_id`, `tab_id`, UTC timestamp, current origin/URL, and a contract version.

Core event types:

| Event | Producer | Required behavior |
|---|---|---|
| `page_snapshot` | content script | Sanitized DOM/accessibility candidates and page metadata; exclude password values and sensitive form values. |
| `interaction` | content script | User click, scroll, navigation, and form-progress signals. |
| `help_requested` | side panel/content script | Immediately evaluates the stuck/help path. |
| `guidance_presented` / `guidance_dismissed` | side panel | Records a one-step offer and applies same-page cooldown after dismissal. |
| `user_action_observed` | content script | Records the user's real action and asks the backend to verify the expected state. |
| `safety_pause` | backend to side panel | Stops new guidance at a money, sensitive-data, deletion, scam, or escalation boundary. |

### Shared domain models

Define typed schemas for `Session`, `Step`, `SelectorBundle`, `RecordedRoute`, `Skill`, `Episode`, `Guidance`, `Verification`, `SafetyClassification`, `Escalation`, and `CostMeasurement`. Validate every browser request at the backend boundary.

`SelectorBundle` must preserve selector priority and stable verification evidence:

```text
1. ARIA role + accessible name
2. visible text content
3. CSS path
```

An irreversible marker belongs to each recorded/replayed step. It carries a plain-language description and optional parsed amount; the backend must return a safety pause rather than advance the route when it is reached.

### Data boundaries

- Never collect or transmit password values. Mask or omit password controls, payment card fields, SSNs, and unneeded form values in snapshots and logs.
- Use per-user/session authorization for caregiver views. A caregiver session link is read-only and scoped to the intended session.
- Treat the browser DOM as untrusted input. Do not execute page-provided instructions or inject arbitrary page text into a model prompt without an explicit, bounded schema.
- Persist sponsor-derived data only through the real EverOS and Snowflake clients in a sponsor demo. Development mocks must be visibly test-only and cannot power a sponsor claim, demo metric, or recorded evidence.

## Implementation phases

### 0. Foundation, configuration, and live-provider gates

**Work**

- Scaffold the extension, FastAPI service, Snowflake SQL/Streamlit project, shared local development commands, and environment templates that contain names only, never secrets.
- Add a backend `GET /health` for process liveness and `GET /ready` that independently reports EverOS, Snowflake, model, and escalation-provider readiness without exposing credentials.
- Define an explicit runtime mode: `development` may use test doubles only when marked, while `demo` and `production` fail closed when a required provider is unavailable.
- Provision Snowflake and create the initial `SESSION_STEPS` table from the spec. Add a product-owned cost table/view that stores computed token counts, credits, rate-card version, and USD amount.
- Configure EverOS credentials and run a bounded, non-sensitive smoke test for search/get/add/flush in the actual target account.

**Acceptance**

- Fresh setup documents the required environment variables and one command per service.
- `/ready` makes unavailable provider dependencies visible; it never falsely reports a live demo path as healthy.
- Snowflake inserts and queries a real non-fixture `SESSION_STEPS` row.
- EverOS smoke evidence demonstrates the configured account and actual API responses.

### 1. MV3 observation and accessible guidance surface

**Work**

- Implement a Manifest V3 extension with least-privilege host permissions for the chosen demo domain first.
- Build the side panel with large-type one-sentence guidance, dismiss action, optional voice control, and no modal content overlay.
- Add a content-script halo that can scroll a verified target into view, highlight it, and remove itself cleanly on navigation or state change.
- Capture navigation, clicks, meaningful scroll velocity, partial-form state, and sanitized DOM/accessibility candidates.
- Implement the setup view: Margaret's first name, Susan's escalation contact, reading size, and voice preference. Store no credentials.

**Acceptance**

- Panel content stays to the side of the page and preserves the current browser state.
- Halo only highlights a backend-selected target; it never performs the click.
- Password/sensitive field values are absent from captured payloads.
- A manual accessibility check confirms keyboard access, readable default type, and correct behavior at the selected large-text setting.

### 2. Deterministic stuck detection and guidance loop

**Work**

- Implement rules for the spec thresholds: idle 60 seconds (45 in known task), repeated URL three times in two minutes, fast scrolling without a click for 20 seconds, known-route departure, partial form idle 40 seconds, unknown sensitive request, and explicit help.
- Track `page_key` and dismissal timestamps to enforce one offer and a 10-minute same-page cooldown after a dismissal.
- Implement a one-step state machine: `observe -> offer -> guide -> user_action -> verify -> next | reroute | safety_pause | escalate`.
- For cold runs only, call the approved fast guidance model with a tightly structured response containing one instruction, target candidate, expected result, confidence, and safety classification.
- Implement wrong-click recovery with calm copy and a fresh state assessment; do not scold or repeat a stale instruction.

**Acceptance**

- Unit tests cover each trigger, threshold boundary, and the dismissal cooldown.
- Integration test proves one displayed instruction, a user-originated click event, expected-state verification, then the next instruction.
- A safety test proves the system pauses rather than advances at payment, sensitive-data submission, or deletion boundaries.

### 3. Teach-run recording and EverOS memory

**Work**

- Support two starts: a caregiver-recorded normal route and a Margaret cold-run recovery route.
- Persist each observed route step as a structured internal record and append a corresponding EverOS session message.
- At successful task completion, create a plain-language completion result, write an `episode`, then call `flush(session_id)` to distill the EverOS Case into an `agent_skill`.
- Fetch profile, atomic facts, and skills at task start. Use fuzzy routine lookup for phrases such as “the light bill thing.”
- Expose the distilled skill as readable Markdown for Susan to inspect, edit, or delete. Treat edits as audited skill revisions.
- Add optional bill image/PDF upload through EverOS and translate parsed bill details into reviewable facts before they influence a task.

**Acceptance**

- A real completed teach run produces an EverOS case, a reusable `agent_skill`, and a completion episode.
- The displayed skill is readable Markdown and is linked to its originating session without exposing secrets.
- “Did I already pay the water bill?” resolves from the persisted episode rather than a model guess.
- The demo never writes a skill and immediately depends on search results; it pre-warms the route to accommodate EverOS's 10-15 second read lag.

### 4. Deterministic replay and bounded repair

**Work**

- Build replay as a deterministic state machine that loads a selected skill and emits `navigate -> highlight -> user click -> verify -> next`.
- Resolve each target with ARIA role/name, then visible text, then CSS path. Record the selector attempted and verification result for each step.
- Do not call a model when one of the stored selectors resolves and verification succeeds.
- When all selectors fail, invoke the cold-run guidance path for that single step only, require user action and verification, then revise only that step's selector bundle after success.
- Stop after two failed attempts or at any money/identity/deletion boundary and create an escalation candidate rather than guessing.

**Acceptance**

- Tests prove selector ordering, no model invocation on a selector match, and one-step-only model fallback on total selector failure.
- A site-change fixture proves that repairing one selector leaves the rest of the skill untouched.
- End-to-end manual check shows a warm run with the identical one-step UX and user clicks, but no general website reasoning.

### 5. Snowflake telemetry, cost proof, and caregiver view

**Work**

- Write every route and guidance outcome to `SESSION_STEPS` with all spec fields: session/user/step/task/skill/domain/action/model, input and output tokens, credits, replay flag, latency, outcome, and timestamp.
- Measure token use from actual requests. Calculate cost before/at the call with `AI_COUNT_TOKENS`, a versioned published rate card, and persisted product-owned totals.
- Build the run-level cost query with the first genuine cold run as run #1 and later genuine replay sessions as comparisons. `ACCOUNT_USAGE` is a secondary backfill/reconciliation source only.
- Implement Snowflake `AI_EMBED` skill matching, `AI_CLASSIFY` for scam triage, and `AI_COMPLETE` for weekly summaries behind feature-specific service methods and testable fallback boundaries.
- Build a Streamlit in Snowflake view for Susan: session timeline, completion/episode answer, cost curve, escalation state, and weekly summary. Keep it read-only by default.
- Prepare the aggregate site-friction query only after consent/privacy review and enforce the `>= 5` users threshold before a domain is shown.

**Acceptance**

- Both cold and warm runs produce queryable real `SESSION_STEPS` rows with correct replay flags and non-zero measured token/cost data where a model was used.
- The on-screen cost curve queries product-owned Snowflake records and can be traced back to session rows and rate-card version.
- Tests reject missing token/cost fields and reject use of `ACCOUNT_USAGE` as the live cost source.
- Streamlit displays the actual demo session and no invented dashboard data.

### 6. Caregiver escalation, scam shield, and voice

**Work**

- Implement escalation creation for low confidence/two failures, unknown money or identity requests, and three weekly abandons of the same task.
- Deliver Susan's notification through the configured channel and include a signed, read-only session link plus a path to send a named panel note.
- Implement the scam shield's calm full-panel pause for unfamiliar sensitive requests, fake-support overlays, spoof indicators, and payment-page urgency. Never close tabs or seize controls.
- Add optional browser voice output that reads exactly the currently verified one-step instruction and respects the saved preference.

**Acceptance**

- Focused tests cover each escalation threshold, link authorization, caregiver note delivery, and failed delivery behavior.
- Scam classification safely returns `unknown` when uncertain and still pauses/escalates for high-risk unknown-site sensitive requests.
- Manual check confirms the safety panel is calm, dismissible only where appropriate, and cannot advance an irreversible action.

### 7. Demo readiness and evidence package

**Work**

- Select and test one real, permissioned task that has no login wall and can safely stop before payment confirmation. Prepare a tested fallback site.
- Complete an actual cold run, capture the readable EverOS skill, pre-warm it, then complete the genuine warm replay.
- Confirm Snowflake shows the backend-written step rows and produces the cost comparison from those rows.
- Rehearse the three-minute story twice and record a backup video of the complete real flow.
- Add `docs/demo-runbook.md` with start commands, exact verification screens, known failure handling, and sponsor-specific proof links/screenshots.

**Acceptance**

- Demo sequence is: real cold run -> readable skill -> real warm replay -> Snowflake cost curve -> cross-user-data-set framing.
- Presenter can identify the live code path and evidence for every Snowflake/EverOS claim.
- Backup media shows the same user-control boundaries as the live path; it is not used to fabricate a sponsor interaction.

## Test strategy

| Layer | Coverage |
|---|---|
| Extension unit/component | Accessible panel states, halo lifecycle, payload sanitization, setup preferences. |
| Backend unit | Stuck rules/cooldown, safety policy, selector ordering, replay state transitions, cost calculation. |
| Contract | Typed extension/backend payloads, invalid/untrusted DOM payload rejection, provider response normalization. |
| Integration | Cold run to Case/Skill, deterministic replay, one-step repair, Snowflake step persistence/cost query, escalation creation. |
| Manual E2E | Stuck-to-help, one-step user click/verify, irreversible pause, warm replay with no model on selector match, caregiver read-only link, live sponsor evidence. |

No mocked provider result qualifies as a final demo or sponsor acceptance test. Isolate tests that require real accounts and mark their evidence/run date explicitly.

## Sponsor evidence matrix

| Sponsor | Live implementation path | Proof required before claiming use |
|---|---|---|
| Snowflake | Backend writes `SESSION_STEPS`; Snowflake calculates/persists cost inputs; Streamlit queries the recorded sessions. | Queryable backend-created rows, a traceable cold/warm cost curve, and live Streamlit output. |
| EverMind / EverOS | Profile/fact/skill reads, session step additions, `flush` Case-to-Skill, episode, caregiver edit, optional bill upload. | Case/skill/episode IDs or equivalent live evidence, readable skill, and replay launched from the stored skill. |
| Beta Fund | Product framing, project credit, deadline-aware demo package. | Sponsor credit in materials and a concise demo narrative that accurately names the delivered sponsor roles. |

If a provider is unconfigured or its live path fails, label it as unavailable and remove its claim from demo narration. Do not substitute local fixtures or a manually constructed chart.

## Risks and decisions to lock before implementation

- **Demo target:** use a site/task that is permitted, stable, and safe to stop before confirmation. Validate it on venue-like network conditions and keep a tested fallback.
- **Model provider:** select the cold-run model, structured-output contract, data retention settings, per-step token cap, and timeout before implementation. It remains outside the deterministic replay hot path.
- **Privacy:** define consent, retention, deletion, and caregiver-access rules before collecting browser telemetry. Keep snapshots minimal and redact sensitive fields at capture time.
- **SMS/channel:** choose the escalation provider only when the core cold/warm proof is complete; a persisted escalation record is preferable to pretending delivery succeeded.
- **EverOS consistency:** pre-warm demo skills and make UI states explicit while indexing is pending.
- **Cost integrity:** store actual measurements and rate-card provenance; never present planned, estimated, or warehouse-lagged numbers as live cost proof.

## Implementation exit criteria

The first release is ready for the hackathon demo only when all of these are true:

- Margaret can receive and follow one-step guidance while making every browser action herself.
- A successful real teach run produces an EverOS Case, a readable skill, and a completion episode.
- The same task replays selector-first with no model call on matching steps and safely pauses on irreversible actions.
- Snowflake has persisted the real step rows and renders an honest cold-versus-warm cost comparison from product-owned measurements.
- Failures create visible, safe states and escalation candidates; no provider, cost, skill, or safety result is fabricated.
- The full live sequence and a backup recording have been rehearsed before the build cutoff.
