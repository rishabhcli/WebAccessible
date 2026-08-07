# WebAccessible Implementation Plan

## 1. Purpose, status, and delivery boundary

This is the execution plan for the product behavior in `webaccessible-spec.md` and the live-integration standard in `SPONSORS.md`. It is intentionally more specific than the product spec: it fixes component ownership, contracts, state transitions, storage boundaries, implementation order, test gates, and evidence requirements. The newer `docs/sponsors/BROWSERBASE.md` execution contract supersedes the spec's local MV3/localhost topology for implementation; the spec remains authoritative for user behavior, safety, replay, memory, Snowflake, and demo commitments until its architecture section is reconciled.

### 1.1 Repository baseline

As of August 7, 2026, this repository has live configuration evidence but no application implementation. `docs/SETUP_STATUS.md` records a configured Browserbase account/API key, a successful live EverOS read, and a provisioned/queryable Snowflake `WEBACCESSIBLE.APP.SESSION_STEPS` table. It does not yet contain a WebAccessible-owned Browserbase session, web UI, FastAPI service, provider adapters, migrations in source control, tests, lockfiles, or deployment configuration. The first code task therefore starts at scaffolding and provider contract probes, while preserving the already verified setup evidence.

| Capability | Current evidence | Next proof required |
|---|---|---|
| Browserbase | Authenticated Free-plan project, key, CLI, and unrelated completed managed sessions | WebAccessible-owned create -> Live View -> CDP -> trusted participant input -> explicit terminate round-trip |
| EverOS | Active key and live agent-scope `agent_skill` read | User/agent ownership adapter plus live add -> flush -> Case/Skill/Episode round-trip |
| Snowflake | Service principal, warehouse/database/schema, required table, successful service-user query | Source-controlled migration baseline plus backend-created non-fixture step/call/cost rows and Streamlit lineage |
| Guidance model | No verified model path recorded | Selected provider/model, structured-output probe, retention settings, actual token usage, rate card |
| Web/FastAPI | No application code | Scaffold, contracts, authenticated participant session, Browserbase bridge, tests |
| Paid pilot | Pricing/service definition only | One consented paid/prepaid caregiver activation linked to live Browserbase/EverOS/Snowflake evidence |

Readiness must always use one of these labels:

| Label | Meaning |
|---|---|
| `specified` | The behavior exists only in documentation. |
| `implemented` | Code exists and passes static and unit checks. |
| `locally_verified` | Deterministic integration or browser tests pass with clearly labeled fixtures/test doubles. |
| `provider_verified` | The configured live provider path passes a dated smoke or integration test. |
| `demo_ready` | The exact Browserbase session path, target task, live providers, evidence views, fallback task, and backup recording passed a timed rehearsal. |

No lower state may be described as a higher one. In particular, an SDK import, credential, mock response, local chart, or planned code path is not a live sponsor integration.

### 1.2 Required demo spine

The smallest acceptable vertical slice proves all four claims below with one traceable task:

1. A user receives one-step guidance and performs every real browser click and submit herself.
2. A verified teach run becomes a readable, machine-valid EverOS skill.
3. A later run loads that exact skill revision and replays selector-first with zero model calls when all stored selectors and verification predicates match.
4. Snowflake contains the real cold and warm session rows and renders a cost comparison derived from product-owned measurements.

The critical path is:

```text
provider readiness
  -> Browserbase session + interactive Live View
  -> sanitized browser observation
  -> deterministic stuck/help state
  -> one guided user action + verification
  -> verified teach route
  -> EverOS Case + Skill + Episode/safe outcome
  -> deterministic replay
  -> Snowflake telemetry + cost lineage
  -> timed live demo and evidence capture
```

### 1.3 Non-negotiable invariants

- The FastAPI browser bridge never calls a page element's `click()`, submits a form, types into the target page, accepts a browser permission, closes a target tab, or activates an irreversible control.
- The user performs every real click and submit. A routine selection may explicitly open its saved start URL, but all in-task actions remain user-originated.
- The CDP observer and web UI never read, transmit, log, or store password values. Card, CVV, SSN, bank-account, hidden-token, cookie, and unnecessary form values are also prohibited.
- Browserbase Browser Sessions plus interactive Live View are the only production/demo browser path. Autonomous Browserbase Agent actions are prohibited, and a local browser can only be a visibly labeled test adapter.
- Guidance is one sentence and one target at a time, followed by verification. It is never a checklist of future actions.
- Safety policy overrides cold guidance, replay, repair, and caregiver messages.
- A matching, verified replay step makes no model call. Model use is allowed only for a cold step, live reroute, or one-step repair and must be labeled accordingly.
- No payment, identity submission, or deletion is described as completed without deterministic completion evidence after the real site action.
- Demo and production modes never silently fall back to fixtures, handcrafted skills, estimated provider success, or disconnected dashboard data.
- Snowflake `ACCOUNT_USAGE` is reconciliation/backfill only, never the live cost source.
- EverOS is the persisted skill source. A local cache may accelerate an active session but cannot become sponsor evidence.
- Foresight reminders are an explicit opt-in, separate from activity-memory consent. They appear only
  in the routine chooser, explain the learned timing evidence, can be snoozed, and require a user click
  before an allowlisted routine is opened. Stuck/help prompts remain driven by observable signals.

### 1.4 Scope tiers

| Tier | Included behavior | Delivery rule |
|---|---|---|
| P0 demo spine | Browserbase lifecycle/Live View, setup, observation, explicit help, stuck detector, cold guidance, record/verify, EverOS Case/Skill, replay, one-step repair, Snowflake step/cost proof, safe terminal state | Must work end to end before optional work starts. |
| P1 safety and trust | Irreversible pause, wrong-click recovery, completion memory, skill inspection, provider failure states, basic scam pause | Complete before any external pilot. |
| P2 caregiver | Hosted read-only session history, authenticated named note, delivery status, skill revision/deletion | Requires production authentication/authorization beyond the P0 participant session. |
| P3 optional product depth | Voice output, reviewed bill upload, weekly summary, Cortex Analyst, SMS, broader scam classification | Add only after the spine is provider-verified. |
| P4 aggregate business | Cross-user site-friction index | Requires consent, retention, deletion, tenant isolation, and privacy review. |

Cut order when delivery is at risk: aggregate index, family dashboard polish, SMS, scam classifier, voice, document upload. Never cut the cold-versus-warm proof or user-control boundary.

## 2. Decisions fixed by this plan

These decisions resolve ambiguities in the product spec for the first implementation. Changing one requires updating this plan, affected contracts, and acceptance tests.

### 2.1 Toolchain

- Root: `pnpm` workspace for JavaScript packages, `uv` for Python, and a small `Makefile` for cross-service commands.
- Web UI: TypeScript in strict mode, React, Vite, Vitest, and Testing Library. It embeds the Browserbase interactive Live View beside the one-step guidance panel; it never receives a CDP connection URL or provider key.
- Production browser execution: Browserbase Browser Sessions through CDP, with Browserbase Live View embedded as Margaret's interactive browser surface. Browserbase is the sole production/demo provider; its API key resolves the project and no project ID is configured. Autonomous Browserbase Agent actions and production/demo local-browser fallbacks are prohibited.
- Backend: Python 3.12, FastAPI, Pydantic v2, `httpx`, Browserbase's supported Python SDK, Playwright's async CDP client, the official Snowflake Python connector, the supported EverOS client, Pytest, Ruff, and MyPy.
- Operational state: SQLite behind a repository interface for session state, event idempotency, and the telemetry outbox. This is operational state, not the sponsor memory/system-of-record claim.
- Contracts: backend OpenAPI and checked-in JSON Schema are authoritative; generated TypeScript clients/types are checked for drift in CI.
- Snowflake: versioned SQL migrations and a Streamlit app that query only product-owned tables/views for the live proof.

Exact package versions are pinned in lockfiles during scaffolding after compatibility probes. The plan does not invent versions before those probes pass.

### 2.2 Navigation authority

`navigate` means one of two explicit behaviors:

1. After the user selects a known routine, the backend may navigate the active Browserbase session through CDP to that skill's allowlisted `start_url`.
2. During the task, FastAPI may scroll/highlight through CDP while Browserbase Live View waits for Margaret's trusted pointer/keyboard action.

The backend never returns arbitrary navigation script. Cross-origin redirects are observed and checked against the skill's allowed origins. Any unrecognized origin pauses replay and requests a new decision.

### 2.3 Routine matching authority

- EverOS search/get supplies the authorized user-specific skill corpus and persistent skill identifiers.
- The first release offers the top matching routine and requires the user to select or confirm it.
- Snowflake `AI_EMBED` may rank descriptors from that authorized corpus after the core path works. It must not introduce a skill ID EverOS did not return for that user.
- The demo claims Snowflake fuzzy matching only after this live re-ranking path has evidence; otherwise the claim is omitted.

### 2.4 Completion and safe stopping

Every task defines a terminal predicate with one of two outcomes:

| Outcome | Meaning | Allowed memory statement |
|---|---|---|
| `completed` | A deterministic post-action predicate proves the task happened. | May write a completion Episode such as "paid on Aug 6". |
| `prepared` | The route reached an irreversible confirmation boundary and intentionally stopped before the real action. | May write only "prepared and stopped before submission". Never "paid" or "completed". |

A model statement, page button label, or caregiver assumption is insufficient completion evidence. For the stage demo, use either a harmless task that can be genuinely completed or truthfully show a money task ending in `prepared`. Maintain a separate harmless completion fixture/live task for the Episode question proof.

### 2.5 Canonical skill representation

An EverOS `agent_skill` is readable Markdown with validated YAML front matter. The front matter is the machine-readable canonical route; the body is the caregiver-readable rendering.

Required front matter:

```yaml
schema_version: 1
skill_key: <client-generated stable uuid>
revision: 1
name: Pay Water Bill
start_url: https://example.test/start
allowed_origins:
  - https://example.test
source_session_id: <uuid>
task_outcome: completed
steps: []
```

Each step contains `step_id`, one instruction template, ordered selector bundle, preconditions, expected transition, timeout, irreversible marker/description, amount source, and repair history. EverOS object IDs and Case IDs live in the provider response envelope and `SKILL_REVISION_LINKS`; they are attached after creation and do not create a circular pre-write requirement. Skill edits use a real YAML parser and JSON Schema validation. A valid edit creates a new immutable revision; it never mutates evidence from an earlier run.

The EverOS provider spike must verify that the actual API can retain and retrieve this structure. If it cannot, the blocker is documented and a supported metadata/object strategy is selected before replay implementation. A handcrafted local Markdown file does not qualify.

### 2.6 Cost scope and truth

The primary demo cost metric is **model inference cost per task run**. It includes hot-path model calls and any Snowflake Cortex calls attributed to that run. EverOS, SMS, warehouse compute, and hosting costs are tracked separately where measurable and are never silently mixed into inference cost.

- Pre-call `AI_COUNT_TOKENS` values are stored as estimates.
- Provider-returned input/output usage is stored as actual usage.
- The immutable rate-card row effective at the call timestamp calculates the displayed amount.
- Advertised values such as "$0.40 versus $0.02" are narrative hypotheses until real rows produce them.
- Warm steps with no model call record zero model tokens/cost, not a missing value.

### 2.7 Caregiver architecture boundary

The P0 WebAccessible session UI and FastAPI service may run locally for the stage demo, but the product must be deployable over authenticated HTTPS for Margaret and Susan to use remotely. Therefore:

- P0 exposes Browserbase Live View only through an authenticated participant session and keeps the API key and CDP `connect_url` server-side.
- The Snowflake Streamlit view may provide provider-authenticated read-only reporting.
- SMS links, remote session history, and named panel notes require hosted FastAPI/web deployment with authenticated caregiver identity, tenant authorization, expiry, and revocation.
- A signed read-only link cannot also authorize a note write or skill edit. Those are separate authenticated capabilities.
- Until the hosted path is deployed and verified, escalation may be persisted as `pending_delivery`, but remote delivery must not be claimed.

### 2.8 Explicitly deferred decisions

- Speech input for the phrase "help" is deferred; P0 explicit help is the WebAccessible session button. Voice output remains optional P3 work.
- Document upload is deferred until provider retention, deletion, and review semantics are confirmed.
- Cross-user analytics are deferred until consent and sparse-cohort review.
- Opt-in foresight reminders are allowed as non-blocking routine suggestions; they never enter the
  stuck/help channel and never authorize target-page action.

## 3. Target architecture

```text
WebAccessible React session UI
  guest entry/routines + one-step panel + safety/completion states
  embedded interactive Browserbase Live View (Margaret's real input)
          |
          | authenticated versioned JSON/SSE
          v
FastAPI service
  participant API -> session orchestrator -> safety policy
       |                    |                  |
       |                    +-> stuck detector (rules only)
       |                    +-> cold guidance adapter (bounded model calls)
       |                    +-> route recorder / replay / repair
       |
       +-> Browserbase session manager -> CDP observer/highlighter/verifier
       +-> SQLite operational store + durable telemetry outbox
       +-> EverOS ownership adapter (profile/fact/Case/Skill/Episode)
       +-> Snowflake adapter (steps, calls, costs, browser lifecycle facts)
                              |
                              v
                 Streamlit in Snowflake (read-only proof/reporting)

Hosted product deployment
  authenticated Margaret session + authenticated Susan history/notes
```

### 3.1 Trust boundaries

| Boundary | Untrusted input | Required control |
|---|---|---|
| Browserbase page -> CDP observer | DOM text, attributes, events, URLs, prompt injection | Allowlisted extraction, length/count limits, no HTML execution, sensitivity filtering, trusted user-action provenance. |
| Live View -> Browserbase page | Participant pointer/keyboard input and stolen Live View URL | Authenticated participant session, no URL logging, short-lived exposure, server-side ownership check, terminal disconnect handling. |
| Web UI -> FastAPI | Stolen session, replayed/out-of-order events | Authenticated user/session binding, strict CORS/CSRF, body limits, UUID idempotency key, state-version checks. |
| FastAPI -> Browserbase | Provider outage/limits, leaked API/CDP capability, orphaned billable session | Server-only secrets/URLs, lifecycle timeout, explicit termination in every terminal/error path, reconciliation sweeper. |
| Backend -> model | Malicious page text and oversized context | Bounded candidate schema, delimiter, strict output schema, candidate-ID grounding, post-model safety policy. |
| Backend -> EverOS/Snowflake | Tenant mix-up, secret leakage, duplicate writes | User/session scoping, adapter validation, minimal payload, idempotent identifiers, redacted logs. |
| Caregiver -> user session | Link theft, cross-user access, unauthorized writes | Authenticated identity, audience/user/session binding, expiry, revocation, separate read/write scopes, audit trail. |

### 3.2 Browser session and UI ownership

**WebAccessible session UI**

- Owns automatic guest entry/routine selection, the one-sentence guidance panel, explicit help/dismiss controls, provider/sync states, and the embedded interactive Live View.
- Receives only the Live View URL and typed participant state for the authorized WebAccessible session. The Browserbase API key and CDP connection URL never enter browser JavaScript.
- Treats `browserbase-disconnected` and stale `server_state_version` as explicit session states rather than silently reusing guidance.
- Renders page/model/caregiver strings as text and accepts no executable script, arbitrary HTML, or synthetic target-page action.

**Browserbase session manager**

- Creates one managed Browser Session per active task, records its provider session ID, obtains server-side CDP connection and interactive Live View URLs, and attaches the CDP client.
- Keeps a lifecycle lease/heartbeat and explicitly terminates the provider session on completion, prepared stop, escalation, abandonment, timeout, backend shutdown, or unrecoverable error.
- Reconciles provider sessions on startup so orphaned sessions are terminated and billing state is recorded.
- Never invokes autonomous Browserbase Agent capability. Provider configuration exposes no agent task method to domain services.

**CDP observer/highlighter/verifier**

- Installs bounded event observation on every new document/tab for navigation, trusted clicks, meaningful scroll windows, non-sensitive form progress, DOM mutations, and post-action state.
- Extracts a bounded list of visible interactive/accessibility candidates rather than raw HTML or input values.
- Resolves selectors against the current page/document ID, requires a unique visible enabled target, scrolls it into view, and draws/removes a non-clicking halo.
- Reports action provenance and verification evidence; it does not decide product or safety policy.
- Removes observation/highlight state on navigation, node removal, stale state version, safety pause, completion, or provider disconnect.

**Guidance panel states**

Explicit UI states:

```text
setup -> routine_list -> observing -> help_offer -> guiding
     -> verifying -> guiding | safety_pause | escalated | completed
     -> provider_unavailable
```

- Exactly one instruction is visible in `guiding`.
- The offer is dismissible and does not cover page content.
- The irreversible state explains the pending real action and amount when safely known, then waits for the user to activate the site's real control.
- Provider and synchronization failures are visible and factual.
- Large text, keyboard operation, 200% zoom, reduced motion, and screen-reader order are acceptance requirements.

### 3.3 Backend ownership

| Module | Responsibility | Must not do |
|---|---|---|
| Event ingress | Validate contract, authentication, sizes, sequence, idempotency, and defense-in-depth redaction. | Interpret DOM prose as instructions. |
| Browserbase adapter | Create/debug/connect/terminate sessions and normalize provider limits/status. | Expose API/CDP secrets or invoke autonomous Agent actions. |
| CDP browser bridge | Observe, sanitize, scroll, highlight, and verify in the managed page. | Click, type, submit, close target tabs, or cross an irreversible boundary. |
| Session orchestrator | Serialize transitions and own authoritative state/version. | Allow two simultaneous guidance steps. |
| Stuck detector | Evaluate deterministic timers/windows and emit reason codes. | Call a model. |
| Guidance service | Ask for one grounded cold/repair decision and validate it. | Execute page actions or bypass safety. |
| Route recorder | Save only verified user-originated steps and compile a skill candidate. | Mark completion from model prose. |
| Replay engine | Resolve exact skill revision, selector order, and verification predicate. | Call a model on a matching verified step. |
| Repair service | Repair only the current failed step and create a new revision after verification. | Rewrite unrelated steps. |
| Safety policy | Classify money, identity, deletion, unknown-site, low-confidence, and repeat-failure boundaries. | Yield to guidance or caregiver text. |
| EverOS adapter | Normalize live provider search/get/add/flush/edit/upload behavior and IDs. | Invent a skill or episode on provider failure. |
| Snowflake adapter | Idempotently sync events/calls/costs and expose lineage queries. | Put warehouse latency on the click-response path. |
| Escalation service | Persist state, attempt delivery, record receipt/failure. | Report delivery before receipt. |

## 4. Repository structure to create

```text
.
|-- .github/
|   `-- workflows/
|       `-- ci.yml
|-- Makefile
|-- package.json
|-- pnpm-workspace.yaml
|-- pyproject.toml
|-- .env.example
|-- .tool-versions
|-- web/
|   |-- package.json
|   |-- vite.config.ts
|   |-- src/
|   |   |-- App.tsx
|   |   |-- api/
|   |   |   `-- client.generated.ts
|   |   |-- session/
|   |   |   |-- BrowserLiveView.tsx
|   |   |   |-- GuidancePanel.tsx
|   |   |   |-- state.ts
|   |   |   `-- useSessionEvents.ts
|   |   |-- routines/
|   |   `-- shared/
|   `-- tests/
|       |-- unit/
|       |-- component/
|       `-- e2e/
|-- backend/
|   |-- app/
|   |   |-- main.py
|   |   |-- config.py
|   |   |-- api/
|   |   |-- contracts/
|   |   |-- domain/
|   |   |   |-- events.py
|   |   |   |-- sessions.py
|   |   |   |-- guidance.py
|   |   |   |-- skills.py
|   |   |   `-- safety.py
|   |   |-- services/
|   |   |   |-- orchestrator.py
|   |   |   |-- stuck_detector.py
|   |   |   |-- route_recorder.py
|   |   |   |-- replay.py
|   |   |   |-- repair.py
|   |   |   |-- completion.py
|   |   |   |-- browser_lifecycle.py
|   |   |   `-- cost_calculator.py
|   |   |-- browser/
|   |   |   |-- observer.py
|   |   |   |-- candidate_extractor.py
|   |   |   |-- sanitizer.py
|   |   |   |-- selector_resolver.py
|   |   |   |-- verifier.py
|   |   |   `-- highlighter.py
|   |   |-- integrations/
|   |   |   |-- browserbase/
|   |   |   |-- model/
|   |   |   |-- everos/
|   |   |   |-- snowflake/
|   |   |   `-- escalation/
|   |   `-- persistence/
|   |       |-- sqlite.py
|   |       `-- outbox.py
|   `-- tests/
|       |-- unit/
|       |-- contract/
|       |-- integration/
|       `-- live/
|-- contracts/
|   |-- event-envelope.schema.json
|   |-- backend-command.schema.json
|   |-- guidance-decision.schema.json
|   `-- skill.schema.json
|-- fixtures/
|   |-- sites/
|   |-- snapshots/
|   |-- skills/
|   `-- providers/
|-- snowflake/
|   |-- migrations/
|   |-- queries/
|   |-- streamlit/
|   `-- tests/
|-- scripts/
|   |-- generate-contracts.sh
|   |-- live-readiness.sh
|   `-- collect-demo-evidence.sh
`-- docs/
    |-- decisions/
    |-- threat-model.md
    |-- privacy-data-map.md
    |-- demo-runbook.md
    |-- evidence-manifest.md
    `-- sponsor-evidence.md
```

Generated files must say how they were generated. Secrets and provider account locators do not enter the repository.

## 5. Contracts and state definitions

### 5.1 Event envelope

All browser events use the same envelope:

```text
contract_version: literal version
event_id: UUID, globally unique idempotency key
session_id: UUID
user_id: opaque backend identifier
browserbase_session_id: opaque provider session identifier
page_id: backend-assigned identifier for the active Browserbase tab
page_instance_id: UUID changed on full document navigation
sequence_no: monotonically increasing within page instance
occurred_at: UTC RFC3339 timestamp
origin: scheme + host + optional non-default port
redacted_path: normalized path, no query or fragment
event_type: closed enum
payload: event-specific typed object
```

Closed P0 event types:

`session_started`, `page_observed`, `navigation_observed`, `interaction_observed`, `form_progress_observed`, `help_requested`, `guidance_presented`, `guidance_dismissed`, `target_resolved`, `user_action_observed`, `verification_observed`, `task_abandoned`, and `session_ended`.

Rules:

- Mutating API requests also send `Idempotency-Key: <event_id>`.
- The server acknowledges the highest accepted sequence and returns `server_state_version`.
- A duplicate `event_id` returns the original result without a second transition or telemetry row.
- Out-of-order events may be stored for audit but cannot regress the session state.
- Payloads over the configured byte/candidate/text limits are rejected, not truncated invisibly.

### 5.2 Element candidate

```text
candidate_id: opaque handle valid only for page_instance_id
role: normalized ARIA/implicit role or null
accessible_name: bounded visible/accessibility name or null
visible_text: bounded normalized text or null
tag_name: closed allowlist
input_type: normalized type or null
visible: boolean
enabled: boolean
focusable: boolean
bounding_rect: x/y/width/height rounded values
href_origin: optional
href_redacted_path: optional
sensitivity_flags: closed enum array
```

The candidate extractor never includes an input's value. For form progress it reports only an opaque control fingerprint plus boolean `dirty`/`validity_changed`; sensitive control fingerprints are excluded entirely. Full HTML, hidden text, scripts, styles, comments, cookies, storage, query strings, and autofill values never enter the payload.

### 5.3 Backend command

```text
command_id: UUID
session_id: UUID
server_state_version: integer
command_type: closed enum
page_instance_id: UUID or null
instruction: one plain-text sentence or null
target: candidate_id + selector bundle or null
expected_transition: verification predicate or null
safety: structured safety presentation or null
```

The WebAccessible UI renders `instruction` as text, never HTML. A command cannot contain code, a synthetic target-page action, a credential, a CDP connection URL, or a raw provider response. Target resolution/highlighting stays server-side in the CDP bridge.

### 5.4 Guidance decision

The model adapter must return and validate:

```text
instruction: one sentence, no list/newline
target_candidate_id: one ID from the submitted candidate set
expected_transition: one supported deterministic predicate
confidence: number from 0 to 1
safety_classification: safe | money | identity | deletion | suspicious | unknown
amount: optional decimal + currency + source
rationale_code: closed internal enum
```

Validation occurs in this order:

1. Parse strict structured output.
2. Reject unknown fields, excessive lengths, missing target, or unsupported predicate.
3. Confirm the target ID exists in the current candidate set.
4. Run safety policy after the model result.
5. Ask the CDP browser bridge to resolve the target against the current Browserbase page instance.
6. Present only after unique visible enabled resolution succeeds.

Timeout, malformed output, low confidence, stale page, or unresolved target produces `safety_pause`/`escalate` or a factual unavailable state. It never produces a guessed highlight.

### 5.5 Selector and verification contract

Every recorded step stores selectors in the mandated order:

1. ARIA role plus exact normalized accessible name.
2. Exact normalized visible text, scoped to an allowlisted interactive element type.
3. CSS path generated from stable attributes and ancestry, with positional selectors used only as a last resort.

A selector match is acceptable only if exactly one element is visible, enabled, inside an allowed origin/frame, and consistent with the recorded element kind. Multiple matches count as failure.

Supported P0 verification predicates:

- `url_path_equals` or `url_path_matches` within an allowed origin, ignoring query/fragment.
- `element_present` or `element_absent` using a verification selector bundle.
- `aria_state_equals` for a named state such as expanded/selected/checked.
- `visible_text_present` using bounded non-sensitive normalized text.
- `page_title_contains` for non-sensitive title text.
- `safe_terminal_reached` for the defined pre-confirmation boundary.

Model prose alone is never a predicate. Verification must use a fresh page observation after a trusted user action and before the next instruction.

### 5.6 Session state machine

```text
CREATED
  -> OBSERVING
  -> HELP_OFFERED
  -> GUIDING
  -> AWAITING_USER_ACTION
  -> VERIFYING
       -> GUIDING              expected state verified, more steps
       -> REROUTING            wrong action or route divergence
       -> REPAIRING            all stored selectors/predicate failed
       -> SAFETY_PAUSED        irreversible or suspicious boundary
       -> COMPLETED            deterministic completed terminal
       -> PREPARED             safe pre-confirmation terminal
  -> ESCALATED
  -> ABANDONED
  -> FAILED
```

Safety, completion, prepared, abandoned, and failed are terminal for automatic progression. Resume from `SAFETY_PAUSED` requires a new trusted page action or an explicit new task decision; a panel acknowledgement never activates the real control.

The orchestrator serializes transitions per session. Each accepted transition increments `server_state_version` and emits at most one current panel command.

### 5.7 Deterministic stuck definitions

The spec thresholds remain unchanged; the implementation definitions are:

- `productive_interaction`: trusted click on an enabled interactive element, allowed form-progress change, full navigation, or successful step verification. Scrolling alone is not productive.
- `page_key`: lowercased origin plus normalized path; query and fragment removed; duplicate/trailing slashes normalized. Later site adapters may supply route templates.
- `same_url`: equal `page_key`.
- `fast_scrolling`: at least four scroll events and cumulative absolute movement of three viewport heights within a rolling 20-second window, with no productive interaction.
- `partly_filled`: at least one allowed non-sensitive control changed from its baseline; only the boolean state is retained.
- `known_site`: an origin in a reviewed skill, explicit profile fact, or deployment allowlist.
- `known_route_departure`: active replay/known task no longer satisfies the current step's allowed origins/preconditions.
- `abandoned`: an active task ends through explicit cancel, tab close, or 10 minutes without a task event before a terminal state.
- `week`: rolling seven 24-hour periods evaluated in the user's stored timezone; UTC remains the persisted timestamp.

Trigger behavior:

| Reason code | Threshold |
|---|---|
| `idle` | 60 seconds, or 45 inside a known task |
| `url_loop` | Third visit to same `page_key` within two minutes |
| `scroll_loop` | Fast-scrolling definition sustained for 20 seconds |
| `route_departure` | Immediate |
| `partial_form_idle` | 40 seconds |
| `unknown_sensitive_request` | Immediate safety evaluation |
| `explicit_help` | Immediate |

Only one offer may exist at a time. Dismissal records `(user_id, page_key, dismissed_at)` and suppresses ambient offers on that page for ten minutes. Explicit help still works during cooldown.

### 5.8 API surface

| Method and path | Purpose | P0 |
|---|---|---|
| `GET /health` | Process liveness only | Yes |
| `GET /ready` | Per-capability provider/configuration readiness and overall mode result | Yes |
| `POST /v1/participant-sessions` | Authenticate/bind Margaret or Susan to a scoped WebAccessible session | Yes |
| `POST /v1/sessions` | Start observe, record, cold, or replay session | Yes |
| `POST /v1/sessions/{id}/browser` | Create and attach the owned Browserbase session | Yes |
| `GET /v1/sessions/{id}/browser/live-view` | Return Live View URL only to the authorized active participant | Yes |
| `POST /v1/sessions/{id}/browser:stop` | Idempotently terminate the Browserbase session and record reason | Yes |
| `POST /v1/sessions/{id}/events:batch` | Idempotent event ingestion and current command response | Yes |
| `GET /v1/sessions/{id}` | Current state/version/sync status | Yes |
| `POST /v1/tasks:resolve` | Return authorized routine candidates | Yes |
| `POST /v1/tasks/{id}:start` | Start selected cold or replay task | Yes |
| `POST /v1/tasks/{id}:end` | Explicit cancel/abandon; cannot declare completion | Yes |
| `GET /v1/routines` | List EverOS-backed routines | Yes |
| `GET /v1/reminders` | List currently due, consent-gated learned-routine suggestions | P1 |
| `POST /v1/reminders/{id}:dismiss` | Snooze one suggestion without starting browser work | P1 |
| `POST /v1/reminders/{id}:accept` | Record permission and create the ordinary guided task session | P1 |
| `GET /v1/skills/{id}` | Read validated current revision | Yes |
| `PATCH /v1/skills/{id}` | Validated audited revision | P2 |
| `DELETE /v1/skills/{id}` | Authorized deletion and cache invalidation | P2 |
| `GET /v1/episodes:answer` | Deterministic completion lookup | P1 |
| `POST /v1/uploads` | Reviewed bill upload flow | P3 |
| `POST /v1/escalations/{id}/notes` | Authenticated caregiver note | P2 hosted only |

`/ready` reports `configured`, `reachable`, `authorized`, `last_checked_at`, `latency_ms`, and a non-secret error code independently for Browserbase create/debug/CDP/terminate, model, EverOS, Snowflake, and escalation delivery. `demo` mode is not ready if a capability required by the selected demo path fails or the Browserbase plan has no available session capacity.

## 6. Persistence, telemetry, and cost

### 6.1 Ownership

| Store | Owns | Does not own |
|---|---|---|
| Web session storage | Short-lived authenticated participant/UI recovery state | Provider keys/CDP URLs, skills, passwords, authoritative task state |
| SQLite operational store | Active state, event ledger, idempotency, derived activity/reminder index, provider operation status, telemetry outbox | Sponsor proof or long-term caregiver memory |
| Browserbase | Active managed Chrome session, interactive Live View, provider session recording/metadata | Product safety decisions, task memory, autonomous target actions |
| EverOS | Profile, reviewed facts, Case, Skill, consented activity Episode and foresight | Browser authorization, click execution, safety policy |
| Snowflake | Session/step telemetry, model-call/cost ledger, escalation/reporting facts | Interactive click-loop state or raw sensitive DOM |

### 6.2 EverOS lifecycle

**Task start**

1. Load user-owned `profile`, `atomic_fact`, and Episode context with `user_id`; load `agent_case` and `agent_skill` with the stable per-user `agent_id = webaccessible:{user_id}` through the ownership adapter.
2. Normalize provider results into internal typed objects.
3. Offer candidate routine; do not start an irreversible task from fuzzy similarity alone.
4. Record returned provider IDs and indexing state.

The rest of the backend addresses memory by WebAccessible `user_id`; only the EverOS adapter translates to the provider's verified user-owned versus agent-owned scopes. Cross-user negative tests must prove that changing either identifier cannot retrieve another user's facts, Cases, Skills, or Episodes.

**Consented activity and foresight**

1. Instant guest sessions keep activity-memory and proactive-reminder permission off; reminders cannot
   be enabled without activity memory.
2. Each accepted managed-session event is idempotently indexed using task, safe origin, kind, outcome,
   and participant-local time. Sensitive payload values, path/query, content, and raw DOM are excluded.
3. At a terminal outcome, a deterministic session understanding and any learned timing pattern are
   written to EverOS. SQLite remains only the operational idempotency/derived-query cache.
4. After two or more task starts, deterministic recurrence inference may produce daily, weekly, or
   monthly foresight. The in-app reminder explains its evidence and respects accept/snooze state.
5. Accept creates a normal session and may open the saved allowlisted start URL; the browser bridge's
   no-click/no-type/no-submit boundary is unchanged.

**Teach completion**

1. Confirm each route step has trusted action provenance and verification evidence.
2. Compile and schema-validate the skill Markdown.
3. Append sanitized structured step messages with `add`.
4. Write an Episode only for truthful `completed` or `prepared` outcome language.
5. Call `flush(session_id)` and retain returned/located Case and Skill IDs.
6. Retrieve by direct known ID when supported; do not depend on immediate search during the 10-15 second index window.
7. Mark `provider_verified` only after live retrieval and schema validation.

**Repair/edit**

- Copy the current revision, change only the verified failed step, increment revision, preserve `source_case_id`, append repair metadata, validate, and write through the supported provider edit/add path.
- Keep old revision linkage for audit and demo traceability.
- Failed provider writes leave the current revision active and show `repair_not_saved`.

### 6.3 Snowflake tables

Keep the required `SESSION_STEPS` columns from the spec and add identifiers/provenance through additive migrations:

- `event_id`, `schema_version`, `run_id`, `step_id`, `guidance_mode` (`cold|replay|repair|none`), `sync_attempt`, and `source_environment`.
- Preserve the required outcomes `ok`, `wrong_click`, `stuck`, and `escalated`; richer transition detail belongs in `action`/companion tables.

Supporting product-owned tables:

| Table | Purpose |
|---|---|
| `SESSION_RUNS` | One row per task run, user/task identity, mode, terminal outcome, start/end, fixture flag, build commit. |
| `BROWSER_SESSIONS` | WebAccessible session, Browserbase session ID, create/CDP/Live View/terminate timestamps, status, terminal reason, provider-limit state, Agent-surface-used flag fixed false. |
| `MODEL_CALLS` | Immutable call ID, step/event link, provider/model/version, actual and estimated tokens, latency, status, provider response ID hash. |
| `COST_RATE_CARDS` | Effective-dated model/token-class unit price, currency, source URL/reference, version, rounding rule. |
| `MODEL_COSTS` | Call ID, actual token quantities, rate-card version, calculated amount/credits/USD, calculation timestamp. |
| `TELEMETRY_INGESTION` | Event ID, payload hash, first/last attempt, synchronized status for idempotency/reconciliation. |
| `ESCALATIONS` | Reason, session, status, delivery channel/attempt/receipt, caregiver response metadata. |
| `SKILL_REVISION_LINKS` | Skill/revision/source-session linkage without duplicating full sensitive skill content. |

Use `MERGE` keyed by stable IDs for retry safety. Snowflake constraints alone are not relied upon for uniqueness; reconciliation queries flag duplicates, gaps, and incomplete sessions.

### 6.4 Outbox and degraded behavior

- The click loop writes an accepted transition and outbox record in one operational transaction, then updates the participant UI without waiting on warehouse insertion.
- The synchronizer retries with bounded exponential backoff and stable event/call IDs.
- `sync_pending`, `sync_failed`, and `synced` are visible session/evidence states.
- Demo mode refuses to start the sponsor proof when Snowflake is unavailable. A mid-run outage enters visible degraded state; unsynced rows never power the chart or sponsor claim.
- Browserbase create/capacity/CDP failure blocks target browsing visibly. A created session that cannot attach is terminated immediately; a termination failure enters reconciliation and pages an operator rather than being marked stopped.
- EverOS failure prevents skill/Episode claims. Model failure prevents cold/repair guidance but does not corrupt a loaded deterministic replay. Safety rules remain available.

### 6.5 Cost calculation

For each model/Cortex call:

1. Create `call_id` before dispatch and link it to session/event/step/mode.
2. Store pre-call input estimate separately.
3. Dispatch once through an idempotent adapter where supported.
4. Store provider-reported actual input, cached input, reasoning, and output token classes as available.
5. Select the effective rate-card row for the exact model/version and timestamp.
6. Calculate with decimal arithmetic and persist the unrounded inputs plus documented rounded display value.
7. Do not guess when usage or rate is unknown; mark cost `unavailable` and block the cost-proof gate.
8. Aggregate by `user_id`, stable `task_id`, and `run_id`; exclude fixtures and incomplete/abandoned rehearsals from the primary curve.

The Streamlit point must drill through to `SESSION_RUNS -> SESSION_STEPS -> MODEL_CALLS -> MODEL_COSTS -> COST_RATE_CARDS`.

### 6.6 Data minimization and lifecycle

Before any non-fixture collection, write `docs/privacy-data-map.md` with field-level source, purpose, sink, retention, deletion, and access role. Minimum rules:

- Persist domain by default, not full URL. Paths are redacted and retained only where required for a skill.
- Never persist raw DOM snapshots in Snowflake. Short-lived bounded candidate snapshots in operational state expire after the session unless explicitly retained as a redacted test artifact.
- Store caregiver contact only in the service responsible for delivery; logs and Snowflake use an opaque caregiver ID.
- Uploaded account numbers are minimized to reviewed necessary fields and preferably last four digits.
- Define cascading deletion across local state, EverOS, Snowflake, evidence media, and caches before external pilot.
- Aggregate domain reporting requires consent and at least five distinct users; sparse slices are suppressed.

## 7. Implementation work packages

Each package has explicit dependencies and a gate. A package is complete only when its acceptance evidence exists.

### WP-00: Decision record and scaffold

**Depends on:** nothing.

**Files:** root toolchain files, `docs/decisions/*`, `docs/privacy-data-map.md`, initial directories.

**Tasks**

- Record the demo target and fallback, allowed origins, safe terminal predicate, model choice/retention settings, rate-card source, provider account aliases, and excluded claims.
- Record the navigation, skill schema, completion, matcher, caregiver, and cost decisions from section 2 as architecture decision records.
- Create pinned toolchains, workspace scripts, environment-variable-name template, formatting/lint/type/test commands, and CI skeleton.
- Add runtime modes: `test`, `development`, `demo`, `production`. Any test double adds a visible `fixture_mode` marker and cannot load in demo/production.
- Configure signed, short-lived participant sessions and CSRF protection; provider secrets remain server-side.
- Add `GET /health` and typed `/ready` with truthful current statuses for configured, provider-verified, and still-unverified capabilities.

**Acceptance gate G0**

- Fresh checkout has documented one-command setup and one command per service/test layer.
- Static checks run even before feature code exists.
- Secret scan passes; `.env.example` contains names and safe descriptions only.
- `/ready` truthfully reflects the already verified EverOS/Snowflake setup while distinguishing it from unverified WebAccessible write/session paths.
- No demo target lacks a written safe terminal/completion predicate.

### WP-01: Provider contract spikes and schemas

**Depends on:** WP-00.

**Files:** `backend/app/integrations/*`, `contracts/*`, `snowflake/migrations/*`, `backend/tests/live/*`, sponsor evidence docs.

**Tasks**

- Browserbase: create a disposable managed session through the backend adapter, obtain Live View and CDP data server-side, attach with Playwright, prove an interactive Live View click arrives as a trusted user action, then explicitly terminate the session. Record provider session/start/stop evidence without secrets.
- EverOS: prove live `search`, `get`, `add`, `flush`, and retrieval of Case/Skill/Episode using non-sensitive data. Measure index lag and verify how structured skill metadata survives.
- Snowflake: inspect and migration-baseline the existing `WEBACCESSIBLE.APP` schema, insert/query one backend-created non-fixture row, run `AI_COUNT_TOKENS`, and verify Streamlit connectivity without sample metrics.
- Model: prove strict structured output, usage metadata, timeout behavior, token limits, and retention configuration.
- Freeze JSON schemas for event, command, guidance, selector, verification, safety, skill, model call, and readiness result.
- Generate OpenAPI and TypeScript contract types; add drift check.
- Write explicit adapter error taxonomy: `unconfigured`, `unauthorized`, `unreachable`, `capacity_exhausted`, `session_limit`, `rate_limited`, `timeout`, `disconnected`, `termination_failed`, `invalid_response`, `indexing`, `write_failed`.

**Acceptance gate G1**

- Dated live response IDs/query IDs are recorded without secrets.
- A WebAccessible-owned Browserbase session has create, Live View/CDP attach, trusted participant input, and explicit termination evidence. Existing unrelated dashboard sessions do not satisfy this gate.
- EverOS round-trip returns a schema-valid live skill or the implementation is blocked with the actual unsupported behavior documented.
- Snowflake holds and returns a non-fixture backend row.
- Model returns schema-valid grounded output and actual usage fields.
- Demo mode fails readiness if any required capability is unavailable.

### WP-02: Browserbase lifecycle, CDP observation, and session UI

**Depends on:** WP-00 contract skeleton; can overlap late WP-01.

**Files:** `web/src/*`, `backend/app/browser/*`, Browserbase adapter/lifecycle service, UI/CDP tests, fixture pages.

**Tasks**

- Implement Browserbase create/debug/CDP attach/terminate behind a narrow adapter that has no autonomous Agent task method.
- Implement lifecycle ownership, session lease, maximum duration, terminal cleanup, shutdown hook, startup orphan reconciliation, and idempotent stop.
- Build the participant session UI with automatic passwordless guest entry, routine selection, interactive Live View iframe, and all P0 guidance/pause/completion/provider states using text-only rendering for external strings.
- Keep API key and CDP connection URL server-side. Authorize the Live View lookup by participant plus WebAccessible session and avoid logging/caching the URL.
- Install CDP observation for each new page/document and implement bounded candidate extraction, sensitivity classification, URL redaction, candidate limits, and golden sanitized snapshots.
- Capture trusted participant clicks/keyboard-driven activations, navigation, scroll windows, and non-sensitive form-progress booleans without capturing entered values.
- Implement selector resolution, target freshness, scroll-into-view, non-clicking halo placement, mutation/navigation cleanup, and verification evidence.
- Handle Live View disconnect, new tabs, provider timeout/limit, and explicit participant stop. Add explicit help; do not request microphone permission in P0.

**Acceptance gate G2**

- Packet/snapshot tests prove forbidden values are absent from CDP events, API messages, logs, and UI state.
- Instrumentation proves the browser bridge never synthesizes click/submit/type actions and the Browserbase Agent surface is never called.
- Halo renders only on a unique visible enabled current target and cleans up in every lifecycle case.
- Backend restart/disconnect either reattaches to the owned session safely or terminates it; no orphaned session is marked stopped without provider confirmation.
- An interactive Live View user action is distinguishable from backend CDP activity and advances only through trusted participant provenance.
- Keyboard-only, largest text, 200% zoom, and screen-reader smoke checks pass.

### WP-03: Event ingress, orchestration, and stuck detection

**Depends on:** WP-01 schemas and WP-02 event emission.

**Files:** backend contracts/domain/services/persistence, unit/contract tests.

**Tasks**

- Implement authenticated participant session binding, exact web-origin CORS, CSRF protection, and per-session authorization. Local development may bind loopback; production is HTTPS-only.
- Validate envelopes, sizes, enums, sequence, current page instance, idempotency, and defense-in-depth redaction.
- Implement SQLite event ledger and transactional session state/version updates.
- Implement the full session state machine with illegal-transition tests.
- Implement all stuck definitions and thresholds from section 5.7 with a fake monotonic clock.
- Enforce one current offer, same-page cooldown, explicit-help bypass, and concurrent-trigger deduplication.
- Return current typed state in the event acknowledgement and use SSE for server-to-UI provider/guidance updates with state-version resumption.

**Acceptance gate G3**

- Boundary tests pass at one unit before, exactly at, and one unit after every timer/count threshold.
- Three simultaneous stuck signals create one offer and one canonical transition.
- A dismissal suppresses ambient help until ten minutes and does not suppress explicit help.
- Duplicate/out-of-order/replayed events cannot duplicate or regress guidance.
- Cross-site, wrong-user, stale-session, and replayed web API calls are denied.

### WP-04: Cold guidance and one-step verification

**Depends on:** WP-01 model adapter, WP-02 target resolver, WP-03 orchestrator.

**Files:** guidance/safety services, model adapter, contract/integration tests.

**Tasks**

- Build the bounded prompt from task intent, reviewed profile/facts, current candidate set, last verified state, and safety policy. Do not send raw HTML.
- Enforce strict decision validation and candidate grounding in the six-step order from section 5.4.
- Present one instruction, then wait for a trusted user action and a fresh verification observation.
- Record selector alternatives and predicate evidence only after verification.
- Implement calm wrong-click handling from the current page; stale guidance is cleared before reroute.
- Apply irreversible and unknown-sensitive safety policy after model output and before presentation.
- Add per-call time/token budget and factual timeout/unavailable state.

**Acceptance gate G4**

- Browser integration proves `offer -> one guidance -> highlight -> trusted user click -> verify -> next`.
- Prompt-injection fixtures cannot select an unknown target, execute text, or bypass safety.
- Wrong click never advances the recorded route and produces calm reroute behavior.
- Payment, identity, and deletion fixtures pause before the real action.
- Each model call has one call ledger record with actual usage or explicit unavailable cost.

### WP-05: Teach recording, completion, and EverOS memory

**Depends on:** WP-04 and live EverOS G1.

**Files:** route recorder/completion, EverOS adapter, skill schema/renderer, skill/episode UI, integration/live tests.

**Tasks**

- Support `caregiver_record` and `cold_teach` session modes. Record mode watches silently unless safety policy fires.
- Record only trusted, verified actions; store ordered selector bundles, pre/postconditions, allowed origins, and irreversible metadata.
- Require a deterministic `completed` or `prepared` terminal predicate before compilation.
- Compile canonical YAML-front-matter skill plus readable Markdown body; validate before provider write.
- Stream sanitized events through live EverOS `add`, write truthful Episode outcome, call `flush`, and retain real Case/Skill IDs.
- Expose indexing state and use direct known ID where supported rather than immediate search.
- Implement deterministic Episode lookup for "Did I already pay it?"; no positive answer exists before a `completed` Episode.

**Acceptance gate G5**

- A real harmless teach run produces traceable Case, schema-valid readable Skill, and completed Episode IDs.
- A safe payment demonstration that stops before submit stores `prepared`, never `paid`.
- Rendered skill contains no secrets and links to source session/revision.
- EverOS failure/indexing states are visible; no local file substitutes for provider evidence.
- Episode question tests prove no false positive before completion and exact stored date/amount afterward.

### WP-06: Deterministic replay and bounded repair

**Depends on:** WP-05 live skill and WP-03 state machine.

**Files:** replay/repair services, selector fixtures, integration/E2E/live tests.

**Tasks**

- Resolve a routine to one user-confirmed EverOS skill revision and allowlisted start URL.
- For each step, try ARIA/name, visible text, then CSS path; log every attempted tier and resolution result.
- Ask the CDP browser bridge to revalidate uniqueness/visibility/enabled state immediately before highlighting.
- Wait for trusted user action and stored verification predicate before advancing.
- Assert through the model-call ledger that successful matching steps create zero calls and zero model cost.
- On total selector miss or failed predicate, enter `REPAIRING`, call the bounded cold path for only the current step, verify the user action, and create a new skill revision changing only that step.
- Stop and escalate after two failed attempts or any unknown money/identity/deletion boundary.

**Acceptance gate G6**

- Fixtures prove exact selector order, ambiguity rejection, stale-node handling, and verification predicates.
- A complete warm run has no model calls and retains the same user-facing one-step experience.
- Drift fixture makes one bounded repair call and changes only one step in the new revision.
- Two failures stop; no third guess occurs.
- A live replay launches from the stored EverOS skill ID/revision, not an in-repo fixture.

### WP-07: Snowflake telemetry, cost proof, and Streamlit

**Depends on:** WP-03 event ledger, WP-04 call ledger, WP-06 cold/warm runs, live Snowflake G1.

**Files:** outbox/synchronizer, Snowflake migrations/queries/Streamlit/tests, evidence docs.

**Tasks**

- Create all tables/views in section 6.3 with environment/fixture provenance.
- Sync browser lifecycle, steps, runs, calls, costs, escalation facts, and skill linkage through idempotent `MERGE` operations.
- Validate required fields and reject unknown rate cards, missing replay flags, missing terminal provenance, and duplicate call IDs.
- Implement genuine run ordering partitioned by `user_id` and stable `task_id`.
- Build the cold/warm cost view from actual provider usage and effective rate cards; keep estimates visible but separate.
- Build Streamlit session timeline, outcome/Episode view, cost curve, replay selector evidence, and sync/provider status. Empty data renders "no verified data".
- Add drill-through identifiers/query output for every chart point.
- Implement `AI_EMBED`, `AI_CLASSIFY`, `AI_COMPLETE`, and Analyst only as separately gated features; do not let optional Cortex work block the spine.

**Acceptance gate G7**

- Actual backend-created cold and warm rows are queryable in Snowflake.
- Both runs link to explicitly terminated WebAccessible-owned Browserbase sessions and interactive user-action provenance.
- Warm matching steps show replay true, zero model calls, and zero inference cost.
- Cost totals reconcile to immutable call/rate rows without double counting.
- Chart excludes fixture, incomplete, and unsynced runs and never queries `ACCOUNT_USAGE` for live totals.
- Streamlit displays the exact demo session; each point is traceable to session/call/rate evidence.

### WP-08: Safety, escalation, and caregiver capabilities

**Depends on:** core gates G4-G7. Hosted caregiver work additionally depends on a deployment/auth decision.

**Files:** safety/escalation services, hosted gateway if selected, caregiver views, authorization/failure tests.

**Tasks**

- Persist escalation exactly once for low confidence, two failed attempts, unknown-site money/identity request, or three task abandonments in a rolling seven-day user-local window.
- Add local deterministic scam suspicion signals; call `AI_CLASSIFY` only on bounded redacted evidence when feature enabled.
- Show calm full-panel assistant pause while leaving the page itself operable. Never close, navigate, clear, or click the page.
- Deploy/authenticate the caregiver gateway before producing remote session links.
- Implement separately scoped read-only session access, named note write, skill edit, and deletion. Audit every mutation.
- Persist delivery before attempt and distinguish `pending`, `delivered`, `delivery_failed`, `acknowledged`, and `resolved`.
- Add optional speech synthesis that reads exactly the visible verified instruction and respects preference/reduced motion; do not add speech input implicitly.

**Acceptance gate G8**

- Every escalation threshold creates one scoped record and correct delivery state.
- Valid, expired, tampered, revoked, and wrong-user caregiver tokens behave correctly.
- Delivery failure never appears as delivered.
- Caregiver text cannot bypass target grounding or safety policy.
- Scam fixtures pause without taking page control; uncertain sensitive pages resolve to pause/escalate, not a guessed safe state.

### WP-09: Demo qualification and evidence freeze

**Depends on:** G1-G7; G8 only for claims included in the presentation.

**Files:** `docs/demo-runbook.md`, `docs/evidence-manifest.md`, `docs/sponsor-evidence.md`, final demo assets.

**Tasks**

- Preflight the exact primary and fallback targets with the release web/backend build, Browserbase account/session limits, interactive Live View, venue-like network, provider accounts, and safe terminal predicates.
- Run a genuine cold teach flow and record session/event/call IDs.
- Confirm the live EverOS Case/Skill/Episode or prepared outcome and retain direct skill ID while indexing completes.
- Run a genuine warm replay from that skill and confirm the zero-model invariant.
- Query real Snowflake rows and open the exact Streamlit session/cost curve.
- Capture dated readiness results, Browserbase session/create/terminate evidence, query IDs, provider object IDs, build commit/hash, screenshots, and video/Session Inspector locations in the evidence manifest without secrets.
- Rehearse the exact three-minute story twice. Record a backup of the same genuine user-controlled flow.
- Freeze features/config/dependencies after qualification; only a tested rollback may change the candidate.

**Acceptance gate G9: demo ready**

- Sequence completes in time: cold run -> readable live skill -> warm replay -> real Snowflake cost curve -> privacy-qualified dataset framing.
- Presenter can trace every claim to a live code path and evidence artifact.
- Primary and fallback targets pass in Browserbase; create/CDP/Live View/termination and other provider readiness are green immediately before presentation.
- No real-money submission, fake completion, fixture, disconnected metric, or unsupported sponsor feature appears in narration.
- Backup recording demonstrates the same live-provider and user-control boundaries.

### WP-10: Limited pilot and post-demo product work

**Depends on:** G9 plus security/privacy review.

- Pilot with one consented user/caregiver pair and an explicit domain allowlist.
- Add server-side kill switches for capture, guidance, provider calls, notifications, and aggregate analytics.
- Implement retention/export/deletion jobs and verify cascade behavior.
- Review telemetry, wrong guidance, safety pauses, and provider costs daily during pilot.
- Expand allowed origins only through reviewed site adapters and recorded regression fixtures.
- Enable aggregate site-friction views only after consent and sparse-cohort controls pass.

## 8. Dependency graph and execution order

```text
WP-00 scaffold/decisions
  +-> WP-01 provider probes/contracts --------------------+
  +-> WP-02 Browserbase/CDP/UI -----------------------+   |
                                                      v   v
                                               WP-03 orchestration
                                                      |
                                                      v
                                               WP-04 cold guidance
                                                      |
                                                      v
                                               WP-05 teach/EverOS
                                                      |
                                                      v
                                               WP-06 replay/repair
                                                      |
                                                      v
                                               WP-07 Snowflake proof
                                                      |
                              +-----------------------+------------------+
                              v                                          v
                       WP-08 caregiver/safety                       WP-09 demo
                              |                                          |
                              +-----------------------+------------------+
                                                      v
                                               WP-10 limited pilot
```

Safe parallelism:

- WP-01 provider probes and the WP-02 web UI shell can run after WP-00 schemas are stubbed; CDP implementation waits for the Browserbase spike result.
- Snowflake migrations/cost views can start after the event/call schemas freeze, while browser/UI work continues.
- Fixture-site development, threat modeling, and evidence-manifest templates can run alongside feature packages.

Do not parallelize across an unfrozen shared contract. Contract changes require regenerated types and passing drift tests before dependent branches continue.

## 9. Verification strategy

### 9.1 Test layers

| Layer | Purpose | Provider policy |
|---|---|---|
| Web UI unit/component | Session authorization, Live View/panel states, disconnects, accessibility | Hermetic |
| Browser bridge unit | Sanitization, candidate extraction, halo, selector/verifier, lifecycle | Hermetic adapter |
| Backend unit | Timers, state machine, safety, selector order, cost math | Hermetic |
| Contract | JSON/OpenAPI compatibility, invalid input, closed enums, size limits | Hermetic |
| Integration | UI/backend/CDP-adapter loop, fake providers, outbox, skill compilation | Clearly labeled doubles |
| Browser E2E | Real Chromium user clicks against deterministic fixture sites | Local fixtures, no sponsor claim |
| Live provider | Browserbase/EverOS/Snowflake/model/escalation contracts | Dated actual accounts |
| Demo E2E | Exact target, live providers, evidence views | No fixtures/doubles |

### 9.2 Core requirement matrix

| ID | Behavior | Pass criterion |
|---|---|---|
| STK-01 | 60/45 second idle | Fires once exactly at threshold, never before. |
| STK-02 | URL loop | Third normalized page visit inside two minutes only. |
| STK-03 | Fast scroll | Fires after defined movement/window with no productive action. |
| STK-04 | Partial form | Fires at 40 seconds; no value appears in any sink. |
| STK-05 | Cooldown | Ambient offer suppressed until ten minutes; explicit help works. |
| STK-06 | Concurrent triggers | One offer, one transition, one telemetry event. |
| BRW-01 | Managed lifecycle | Create, CDP attach, Live View, and explicit termination succeed with one owned session ID. |
| BRW-02 | Interactive provenance | Live View click/keyboard action is observed as participant-originated; backend CDP activity cannot impersonate it. |
| BRW-03 | Agent prohibition | No autonomous Browserbase Agent endpoint/method is reachable or called. |
| BRW-04 | Cleanup | Every terminal/error/restart path terminates or visibly reconciles the provider session. |
| BRW-05 | Capacity failure | Free-plan/session limit blocks visibly with no local fallback. |
| CTL-01 | User control | Browser bridge issues no click/submit/type or in-task action; only allowlisted start navigation, observation, scroll/highlight, and verification. |
| CTL-02 | Irreversible action | Pause describes action/amount; only real page action can continue. |
| GUI-01 | Guidance unit | Exactly one sentence, one current target, one verification. |
| GUI-02 | Wrong click | No advance; calm reroute from fresh current state. |
| RPL-01 | Selector order | ARIA/name, visible text, CSS, with ambiguity rejected. |
| RPL-02 | No-model replay | Complete matching warm run records zero calls/tokens/cost. |
| RPL-03 | One-step repair | One bounded call; only failed step changes revision. |
| RPL-04 | Failure ceiling | Second failure escalates; no third guess. |
| MEM-01 | Live lifecycle | Real add/flush produces traceable Case/Skill/Episode or prepared outcome. |
| MEM-02 | Episode truth | No completion answer before proof; exact stored result after. |
| MEM-03 | Index lag | Visible indexing state; no invented/immediate-search skill. |
| TEL-01 | Row completeness | Required fields/replay/outcome/provenance present. |
| TEL-02 | Idempotency | Retry/reorder/reconnect produces one canonical event/call. |
| CST-01 | Actual usage | Stored totals equal provider usage and rate-card math. |
| CST-02 | Cost lineage | Chart point drills through all product-owned source rows. |
| CST-03 | Live-source integrity | Missing product rows shows unavailable, never `ACCOUNT_USAGE` fallback. |
| ESC-01 | Thresholds | Each qualifying condition creates exactly one escalation. |
| ESC-02 | Delivery | Timeout/error persists failed state, never delivered. |
| SEC-01 | Redaction | Password/card/SSN/token values absent from messages, requests, logs, stores, providers. |
| SEC-02 | Prompt injection | Page text cannot change policy, choose unknown target, or execute. |
| SEC-03 | Session auth | Cross-site, wrong-user, replayed/tampered participant requests and Live View lookups are denied. |
| ACC-01 | Accessibility | Keyboard, screen reader, large text, zoom, reduced motion pass. |
| MOD-01 | Runtime modes | Doubles visible only in dev/test; demo/production fail readiness. |

### 9.3 Fixture catalog

Serve deterministic pages from a dedicated test origin:

- Stable harmless multi-step task with deterministic completion.
- ARIA-stable/CSS-drift, text-fallback, CSS-fallback, and total-selector-miss revisions.
- Duplicate labels, hidden/disabled controls, stale nodes, delayed hydration, shadow DOM, iframe, target removal, and history/hash navigation.
- Wrong-click distractor with recoverable route.
- Payment, delete, and identity-submit boundaries with safe fake amounts.
- Partial form containing allowed fields plus password/card/SSN controls.
- Fake-support, phishing, unknown-payment, and legitimate-sensitive safety pages.
- DOM prompt injection, encoded text, oversized candidate sets, and page script attempts to call WebAccessible APIs cross-site.

Supporting fixtures include a frozen monotonic clock, deterministic event factory, golden sanitized candidate snapshots, golden skill revisions, prohibited-value scanner, provider fakes with programmable latency/failure, and a Snowflake test schema whose rows are permanently tagged `source_environment = test`.

### 9.4 Failure injection

| Fault | Required behavior |
|---|---|
| Browserbase create fails/limit reached | Provider blocked state; no local or fixture fallback in demo/production. |
| CDP attach fails after create | Explicitly terminate created session and record failed lifecycle. |
| Live View disconnects | UI shows disconnected; guidance freezes until authorized recovery/termination. |
| FastAPI restarts mid-task | Reattach only after ownership/state checks or terminate/reconcile; no duplicate action/transition. |
| Browserbase termination call fails | Mark `termination_pending`, retry/reconcile, never report stopped without provider evidence. |
| Network delay/disconnect | No stale guidance; factual unavailable/retrying state. |
| DOM changes after guidance | Revalidate and clear halo; do not wait on stale target. |
| Model timeout/malformed/low confidence | No unverified highlight; pause/escalate/unavailable. |
| EverOS add succeeds, flush fails | Case/in-flight status visible; no Skill claim. |
| EverOS index delay | Indexing state and retained known ID only when supported. |
| Snowflake unavailable before demo | `/ready` false and cost proof blocked. |
| Snowflake fails mid-run | Visible unsynced state; chart excludes run. |
| Duplicate/out-of-order telemetry | Idempotent merge and reconciliation, no double count. |
| Missing/stale rate card | Cost unavailable; never guessed. |
| Empty Streamlit query | "No verified data," never sample metrics. |
| Caregiver delivery failure | Persist `delivery_failed`; user is not told Susan received it. |
| System wall-clock change | Monotonic interaction timers; UTC persisted timestamps. |
| Sensitive-data detection in any sink | Release blocker, evidence invalidation, purge/incident procedure. |

### 9.5 Security and privacy gates

Before G8 or external use, `docs/threat-model.md` must cover malicious page/DOM, prompt injection, stolen participant/Live View URL, CSRF, cross-user access, replayed links, leaked CDP capability, orphaned billable sessions, provider compromise/outage, telemetry duplication, and sensitive logging.

Release-blocking checks:

- Explicit allowed target origins, exact web-origin CORS, CSRF protection, and no provider key/CDP URL in client bundles.
- Short-lived participant sessions, authorized Live View lookup, CSP `frame-src` limited to required Browserbase origin, and no Live View URL in logs/analytics.
- Web CSP, no `eval`, dependency audit, lockfiles, and reproducible frontend/backend build hashes.
- Text-only rendering for page/model/caregiver strings.
- Tenant-negative tests for session, skill, Episode, Snowflake, EverOS, and caregiver identifiers.
- Consent, capture pause, retention, export, deletion, and cascade tests.
- No sensitive values in crash reports, traces, prompts, screenshots, or backup recordings.

### 9.6 Performance budgets

Measure on the demo machine and lock final p95 budgets during WP-00. Initial targets:

- Backend event acknowledgement/state decision: <= 150 ms excluding model and network transport.
- Halo placement after command: <= 100 ms on a stable page.
- Deterministic replay decision: <= 300 ms excluding navigation.
- Cold guidance response: <= 3 seconds, then factual retry/unavailable state.
- Snowflake sync: asynchronous; never blocks page guidance.
- Guidance-panel state must not visually flicker or regress during retries.

Budgets are gates only after measured baselines confirm they are realistic; changes must be recorded, not silently loosened.

## 10. Observability and evidence

### 10.1 Structured logs

Allowed fields: trace ID, pseudonymous user ID, WebAccessible session/run, Browserbase session, page/event/step IDs, runtime mode, state transition, stuck reason, selector tier, verification result, provider status, retry count, latency, sync status, skill revision, and rate-card version.

Forbidden fields: form values, raw DOM text, full URLs/query strings, caregiver phone number, account number, prompt body, cookie/token, provider secret, and raw uploaded document content.

### 10.2 Metrics and alerts

Track:

- Stuck reasons, offers, dismissals, cooldown suppressions, accepted help.
- Guidance verification success, wrong clicks, reroutes, pauses, abandonments, escalations.
- Selector tier, ambiguity, total misses, repair count, and model calls by `guidance_mode`.
- Browserbase create/CDP/Live View/terminate duration and failure, active/orphan count, provider limits, EverOS indexing delay, and outbox backlog/sync age.
- Actual tokens/cost by cold/replay/repair and rate-card version.
- Redaction counts, forbidden-data test detections, caregiver authorization denials.

Immediate alerts/release blockers:

- Any model call on a successful matching replay step.
- Any forbidden sensitive value detected in a sink.
- Any fixture/test double loaded in demo mode.
- Any chart sourcing live cost from `ACCOUNT_USAGE` or fixture-tagged rows.
- Any Browserbase Agent call, orphaned session past the cleanup SLA, false completed Episode, cross-user access, untraceable cost, or browser-bridge-generated target action.

### 10.3 Evidence manifest

For each dated qualification run record:

- Build commit plus frontend/backend artifact hashes.
- Runtime mode, target/fallback origins, Browserbase session/region/status/termination reason, and managed Chrome version when available.
- `/ready` timestamp and non-secret results.
- Session/run/event/call IDs.
- Browserbase create, Live View retrieval, CDP attach, participant-input, termination, and Session Inspector evidence references.
- EverOS Case/Skill/Episode IDs and revision.
- Snowflake query IDs and Streamlit session URL/reference.
- Model/rate-card version and cost reconciliation result.
- Screenshots/video locations and capture timestamps.
- Included and explicitly excluded sponsor claims.

Evidence files never contain credentials, raw sensitive DOM, or personal phone/account data.

## 11. Demo runbook requirements

`docs/demo-runbook.md` must contain exact, tested commands and checks:

1. Verify clean working build and artifact hash.
2. Start backend and inspect `/health` and `/ready`.
3. Confirm web/backend build, participant authentication, target allowlist, Browserbase create/CDP/Live View/terminate readiness, and no Agent integration.
4. Confirm Snowflake schema/query access and empty/real-data distinction.
5. Confirm EverOS target user and pre-warmed skill/index state.
6. Run primary target preflight without consuming/altering the qualified baseline unexpectedly.
7. Run cold flow, inspect readable skill, run warm flow, inspect cost curve.
8. State the user-control and safe-stop boundaries accurately.
9. Use the tested fallback only when a named preflight condition fails.
10. Use the backup recording only as a genuine-flow fallback, not as evidence of a currently healthy provider.

The three-minute content remains: who the product serves, a real user-controlled cold run, the readable learned skill, the warm no-model replay, real Snowflake cost proof, and privacy-qualified dataset framing. Do not quote target dollar/latency numbers unless the displayed live evidence matches them.

## 12. Risk register

| Risk | Severity | Detection | Mitigation / blocking rule |
|---|---|---|---|
| Browser bridge synthesizes target action | Critical | Instrument CDP/page APIs and event provenance | Architectural prohibition; release rollback. |
| Autonomous Browserbase Agent path used | Critical | Adapter surface/call audit | No Agent method in adapter; release rollback and claim invalidation. |
| Browserbase session orphaned/billing continues | High | Lifecycle lease and provider reconciliation | Idempotent stop in all terminal/error paths plus sweeper/alert. |
| Browserbase free-plan/session limit | High | Readiness/capacity probe | Visible blocked state; no local fallback; reschedule or fund/upgrade outside code. |
| Live View or CDP capability leaks | Critical | Client bundle/log scan and auth tests | Server-only CDP/key, scoped participant lookup, no logging. |
| Password/card/SSN leak | Critical | Packet/sink scanner | Capture-time omission; release blocker and evidence purge. |
| False payment/completion Episode | Critical | Terminal-predicate tests and audit | Only deterministic post-action evidence may write `completed`. |
| Cross-user caregiver access | Critical | Tenant-negative tests and access logs | Bound identity/session/audience, expiry, revocation. |
| Prompt-injected page controls model | High | Adversarial fixtures | Bounded schema, candidate grounding, post-model safety. |
| Sponsor claim backed by fixture | High | Mode/evidence audit | Remove claim; demo gate fails. |
| Warm replay invokes model | High | Call-ledger assertion/alert | G6/G7 failure. |
| Snowflake outage or empty data | High | Readiness and trace query | Visible unavailable state; block cost proof. |
| EverOS flush/index lag | High | Live timed probe | Retain supported direct ID, show indexing, pre-warm. |
| Canonical skill loses structure | High | Round-trip schema test | Block replay until provider-supported representation exists. |
| Cost double-count/stale rate | High | Reconciliation and lineage tests | Stable call IDs, immutable rate provenance, unavailable on gap. |
| Target-site drift | High | Preflight/canary and selector metrics | Bounded repair, tested fallback, genuine backup. |
| Local demo presented as remote caregiver product | High | Architecture/evidence review | Hosted authenticated web/backend required before remote claim. |
| Unknown money/identity guidance | Critical | Safety fixture suite | Pause/escalate, never guess. |
| Venue network failure | High | Venue-like timed rehearsal | Primary/fallback probes and backup recording. |
| Help nags user | Medium | Cooldown tests/metrics | One offer and same-page ten-minute suppression. |
| Delivery silently fails | Medium | Receipt/timeout tests | Persist and show `delivery_failed`. |
| Large text breaks controls | Medium | Accessibility screenshots/tests | Responsive stable dimensions, wrap/scroll, no overlap. |
| Aggregate re-identification | High | Privacy/sparse-cohort tests | Consent, domain-only labels, >=5 users, suppress slices. |
| Scope expansion breaks demo spine | High | Gate and critical-path review | Optional cut order; freeze at G9. |

## 13. Definition of done

### 13.1 Demo release

All must be true:

- G0-G7 and G9 pass; G8 passes for every caregiver/safety claim included in narration.
- The user receives one accessible instruction and performs every actual page action.
- A real teach run has live EverOS Case/Skill evidence and a truthful completed or prepared outcome.
- The exact live skill revision replays selector-first with zero model calls on every matching step.
- One-step drift repair changes only the verified failed step and stops after two failures.
- Snowflake contains the actual run, step, call, cost, and provenance rows; Streamlit shows the exact sessions.
- Provider, sync, indexing, and delivery failures are visible and never replaced by fixtures.
- A WebAccessible-owned Browserbase session path is live, interactive, explicitly terminated, and recorded; no Agent capability or local demo fallback is used.
- Security redaction, participant/Live View auth, prompt-injection, tenant, user-control, and irreversible-action tests pass.
- The primary/fallback flow and genuine backup recording have been rehearsed and captured before freeze.

### 13.2 External pilot

In addition to demo release:

- Hosted caregiver architecture and authentication are deployed and penetration-tested at the intended scope.
- Consent, retention, export, deletion, cascade, and audit processes pass.
- Capture/provider/notification kill switches are tested.
- Domain adapters and allowed origins are reviewed individually.
- Operational alerting and incident response exist for sensitive leakage, false completion, unsafe guidance, cross-user access, and provider drift.

## 14. Requirement traceability

| Spec requirement | Work packages | Primary evidence |
|---|---|---|
| Guest entry without password handling | WP-00, WP-02 | Participant-entry UI, sink-redaction tests |
| Browserbase managed execution | WP-01, WP-02, WP-09 | Owned session create/CDP/Live View/input/terminate evidence |
| Observable stuck triggers and cooldown | WP-03 | STK boundary/concurrency suite |
| One-step guidance and user click | WP-02, WP-04 | Browser E2E and action provenance |
| Wrong-click reroute | WP-04 | Wrong-click fixture/E2E |
| Irreversible pause | WP-04, WP-08 | Payment/delete/identity safety suite |
| Completion memory | WP-05 | Live Episode ID and truth tests |
| Case to readable Skill | WP-01, WP-05 | Live provider round-trip and schema render |
| Selector-first replay | WP-06 | Selector fixtures and call-ledger zero assertion |
| One-step skill healing | WP-06 | Revision diff and bounded repair call |
| Susan escalation | WP-08 | Persisted state, hosted auth, delivery receipt/failure |
| Scam shield | WP-08 | Bounded classification and non-control E2E |
| Snowflake system of record | WP-01, WP-07 | Backend-created rows and query IDs |
| Honest cold/warm cost curve | WP-07 | Run/call/rate lineage and Streamlit view |
| Cortex feature jobs | WP-07, WP-08 | Separately dated live feature evidence |
| Cross-user site-friction data | WP-10 | Consent/privacy gate and >=5-user query |
| Three-minute genuine demo | WP-09 | Timed checklist, evidence manifest, backup recording |

This plan is complete enough to begin WP-00. It deliberately blocks code that would create a false sense of completion: remote caregiver links without a hosted authenticated path, replay without a provider-valid canonical skill, positive completion memories without proof, and cost charts without product-owned live rows.
