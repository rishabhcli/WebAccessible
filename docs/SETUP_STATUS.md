# Live Integration Setup Status

Code status updated 2026-08-07. Snowflake schema, Streamlit entity, rate-card, and Cortex
guidance evidence was refreshed live during this build; other external-provider evidence is
carried forward from the dated setup work already recorded in this repository. No credentials
are recorded here.

## Status Vocabulary

The application reports one of the following states per provider capability:

| State | Evidence boundary |
|---|---|
| `unconfigured` | One or more required configuration values are absent. |
| `configured` | Required values are present, but a successful provider operation is not asserted. |
| `reachable` | A live provider request returned; required authorization is not yet asserted. |
| `authorized` | The scoped live operation required by the readiness probe succeeded. |
| `unavailable` | The configured provider failed its current check. |
| `capacity_exhausted` | Browserbase has no capacity for the requested managed session. |

These states describe a point-in-time capability check. They do not by themselves prove a
cold teach run, memory write/readback, warm replay, provider termination, synchronized cost
curve, or demo readiness.

## Secret Handling

- `.env` is ignored and contains local development credentials only.
- [`.env.example`](../.env.example) contains variable names and non-secret defaults.
- Fly secrets must be installed with `flyctl secrets set`; they do not belong in `fly.toml`.
- Snowflake CLI credentials remain in the local Snowflake connection store.
- Provider keys, CDP URLs, Live View URLs, and service tokens must not enter source,
  documentation, Snowflake product tables, screenshots, or evidence manifests.

## Built Application Inventory

| Area | Implemented repository surface | Live proof state |
|---|---|---|
| Participant web app | Setup, routine chooser, Browserbase Live View, guidance, voice, help/dismiss, terminal states | Implemented; hosted flow not yet qualified |
| Caregiver web app | Session history, cost view, skill viewer, escalation notes, explicit empty/error states | Implemented; live cross-provider data not yet qualified |
| FastAPI | Health/readiness, signed participant access, session/task/browser/event/SSE/routine/skill/episode/escalation/dashboard APIs | Implemented; Fly deployment not yet evidenced |
| Browser bridge | Browserbase create, Live View, CDP attach, sanitized observation, highlight, verification, termination | Implemented; WebAccessible-owned round-trip not yet evidenced |
| EverOS | Ownership adapter, profile updates, search/read, teach `add`/`flush`, skill and episode retrieval | Implemented; teach write/readback not yet evidenced |
| Snowflake/Cortex | Service connector, structured guidance, token estimate/usage ledger, outbox MERGE, exact rate-card calculator | Implemented; exact live structured adapter call and rate-card readback qualified |
| Snowflake reporting | Four migrations, evidence/reconciliation queries, read-only Streamlit app | Product tables/views and Streamlit entity exist live; task-run drill-through not yet qualified |
| Deployment | Multi-stage Docker image, Fly app/volume config, Snowflake deployment scripts | Authored; no successful deployment recorded |
| CI | Static Python/TypeScript checks and production web build workflow | Authored; no workflow run recorded |

## Provider Evidence Snapshot

### Browserbase

| Item | Current evidence |
|---|---|
| Account/project | Authenticated `Production project` dashboard was inspected on the Free plan. |
| API key | Provisioned in ignored local configuration. |
| Execution path | Code uses Browserbase Browser Sessions, server-only CDP, and interactive Live View; no autonomous Browserbase Agent surface is wired. |
| Current truthful label | `configured` until this application creates and attaches its own active managed session. |
| Missing proof | Create -> Live View -> CDP -> trusted participant input -> explicit provider-confirmed terminate, with captured session ID and timestamps. |

Previously observed unrelated completed Browserbase sessions prove account access, not the
WebAccessible lifecycle.

### EverOS

| Item | Current evidence |
|---|---|
| Account/memory space | Authenticated `default_space` was inspected. |
| API key and SDK | Active key stored outside Git; `everos-cloud==1.0.0` is locked by the project. |
| Retained live proof | Agent-scope `get('agent_skill', agent_id='webaccessible')` succeeded. |
| Ownership contract | User memory uses `user_id`; Case/Skill memory uses stable agent ID `webaccessible:{user_id}`. |
| Missing proof | A real application teach run must return or locate its Case/Skill/Episode IDs, survive indexing, and read the exact skill revision back for replay. |

The retained read proves the configured memory scope. It does not prove the new application
write/flush/readback path.

### Snowflake and Cortex

| Item | Current evidence |
|---|---|
| CLI/service identity | Snowflake CLI 3.24.1 previously connected as `WEBACCESSIBLE_APP` with `WEBACCESSIBLE_APP_ROLE`. |
| Warehouse/database/schema | `WEBACCESSIBLE_WH`, `WEBACCESSIBLE.APP`. |
| Live schema proof | `SHOW TABLES` query `01c63c54-0107-59ea-000f-e9160001ee66` returned all ten product tables; `SHOW VIEWS` query `01c63c54-0107-59eb-000f-e9160001b1ae` returned all eleven evidence views. |
| Live Streamlit proof | `SHOW STREAMLITS` query `01c63c54-0107-59ea-000f-e9160001ee6a` returned `WEBACCESSIBLE_CAREGIVER` in `WEBACCESSIBLE.APP`. This proves entity deployment, not successful browser rendering. |
| Live rate-card proof | Migration query `01c63c4f-0107-5622-000f-e9160001002e` inserted two exact `claude-haiku-4-5` rows; readback query `01c63c4f-0107-59eb-000f-e9160001b1a6` confirmed version `snowflake-cortex-any-region-2026-08-07`. |
| Live Cortex proof | Exact `CortexGuidanceAdapter.decide` queries `01c63c53-0107-59eb-000f-e9160001b1aa` (`AI_COUNT_TOKENS`) and `01c63c53-0107-500e-0000-000fe91661a9` (`AI_COMPLETE`) returned a validated checkbox decision and actual usage of 1,506 input, 230 output, 1,736 total tokens. |
| Current truthful label | Snowflake service access, product schema, Streamlit entity, rate card, and bounded Cortex guidance are `authorized`/live-qualified at the provider boundary. |
| Missing proof | Sync a real participant run into `SESSION_RUNS`, `SESSION_STEPS`, `MODEL_CALLS`, and `MODEL_COSTS`; open the matching Streamlit drill-through; retain the rendered evidence. |

`ACCOUNT_USAGE` remains reconciliation/backfill only. It is not used as the live cost source.
The `/ready` model capability currently follows Snowflake service readiness. The separate
structured Cortex receipt above proves the model operation at this point in time, while `/ready`
still does not perform a billable model invocation.

### Fly

| Item | Current evidence |
|---|---|
| Configuration | `Dockerfile` and `fly.toml` define the bundled API/UI process, HTTPS service, `sjc` region, and persistent `/data` volume. |
| Current proof | No successful `flyctl deploy`, public `/health`, or public `/ready` response is recorded. |
| Missing proof | Provision app/volume/secrets, deploy the current revision, read back status/logs, and run the strict readiness script against the public URL. |

## Exact Deployment Commands

Install the Snowflake schema and Streamlit entity:

```bash
snow connection test --connection webaccessible
SNOWFLAKE_CONNECTION=webaccessible ./scripts/apply-snowflake.sh
SNOWFLAKE_CONNECTION=webaccessible ./scripts/deploy-streamlit.sh
```

Build and deploy the bundled application after Fly secrets and the volume are provisioned:

```bash
pnpm build
flyctl deploy --app webaccessible-care
flyctl status --app webaccessible-care
curl -fsS https://webaccessible-care.fly.dev/health
```

Run the strict provider preflight while a WebAccessible Browserbase task is actively attached:

```bash
API_PUBLIC_URL=https://webaccessible-care.fly.dev ./scripts/live-readiness.sh
```

Full secret installation and one-time Fly provisioning commands are in the root
[`README.md`](../README.md).

## Remaining Live Gates

Only external execution and evidence remain unresolved:

1. Run the repository static/build workflow successfully for the exact revision selected for
   deployment.
2. Sync the first real task's Snowflake run/step/model/cost rows and render that exact run in the
   deployed Streamlit entity.
3. Deploy the bundled API/UI to Fly and capture public health/readiness output without secrets.
4. Complete and explicitly terminate one WebAccessible-owned Browserbase cold teach session.
5. Read back that run's real EverOS Case/Skill/Episode identifiers after indexing.
6. Launch a warm replay from that exact skill revision and capture the zero-model matching
   path.
7. Query the backend-created Snowflake selector/skill lineage rows and retain the matching
   Streamlit drill-through.
8. Freeze the evidence manifest and rehearse the qualified flow. A paid/prepaid Care Plan
   pilot remains a separate Track 2 business proof.

Until those gates have evidence, the accurate status is **implemented, not live-qualified or
demo-ready**.
