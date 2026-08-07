# EverMind / EverOS Implementation Contract

## Role

EverOS is the persistent memory layer that converts an expensive teach run into a cheap, reliable replay. It also keeps caregiver-readable records of preferences, account facts, completed tasks, and routine timing. EverOS does not replace browser safety policy or deterministic replay verification.

## Memory model

| Type | WebAccessible use | Required lifecycle |
|---|---|---|
| `profile` | Reading size, voice preference, capability notes, and guidance tone. | Load at task start; update only through authorized setup/caregiver action. |
| `atomic_fact` | Biller/account context and aliases such as “light bill.” | Search at task start; show caregiver-originated edits as reviewed facts. |
| `agent_case` | Raw successful task trajectory. | Produced from the recorded teach run. |
| `agent_skill` | Readable Markdown route used for replay. | Distilled on successful `flush`; version on repair/edit. |
| `episode` | Completed task with date, amount, and result. | Write only after backend verification of a completion state. |
| `foresight` | Recurring task timing/nudges. | Optional after core replay is proven. |

## Live paths to implement

### Task start

FastAPI searches profile/facts/skills with the user's phrasing and retrieves the routine list. A fuzzy match may offer the likely routine, but must not initiate an irreversible action or bypass user confirmation.

### Teach run to replayable skill

1. Record a caregiver-led or cold-run trajectory as structured local route state.
2. Append sanitized step events to the EverOS session using `add`.
3. On verified completion, write a completion episode and call `flush(session_id)`.
4. Retrieve/identify the resulting `agent_case` and `agent_skill`.
5. Render the skill as readable Markdown with its source session and revision metadata.

The replay engine remains selector-first and deterministic. EverOS stores and retrieves the route; it does not authorize a browser click or a payment.

### Caregiver updates and document upload

Susan can edit explicitly reviewed facts through EverOS's edit path. An optional paper bill image/PDF upload goes through EverOS, then presents extracted biller, account number, typical amount, and due date for review before use.

## Consistency and failure behavior

- EverOS reads can lag roughly 10-15 seconds after a write. Do not write and immediately rely on search during the demo; pre-warm the skill and retain the known skill identifier from the completed run.
- If EverOS is unavailable in demo/production mode, do not offer a made-up skill, completion answer, or memory-backed cost claim. Show that replay/memory is unavailable and retain only clearly labeled local in-flight state.
- Never use a local mock or handcrafted Markdown skill as sponsor-demo evidence.

## Evidence required before demo claim

- A real teach run produces a Case and an `agent_skill` through the live `add`/`flush` path.
- The rendered skill is readable Markdown and is associated with its recorded route.
- A warm replay launches from the stored skill and uses the expected selector-first behavior.
- A persisted episode answers a completion question from memory rather than a model guess.
- Any uploaded bill fact is visibly reviewable and traces to the authorized upload flow.

## Source traceability

- [SPONSORS.md](../../SPONSORS.md), EverMind / EverOS section and proof checklist.
- [webaccessible-spec.md](../../webaccessible-spec.md), sections 2.3-2.5 and 3.
- [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md), phases 3 and 4.
