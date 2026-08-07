# WebAccessible

WebAccessible is a caregiver-supported browser guidance application for older adults. It
detects observable stuck moments, presents one short next step, highlights the relevant
control, and waits for the participant to perform the real action. Verified teach runs are
stored as readable EverOS skills and later replayed selector-first without a model call when
the saved route still matches.

The application code is now present across the React UI, FastAPI service, Browserbase bridge,
EverOS memory adapter, Snowflake telemetry and Cortex adapters, Snowflake migrations, and
Streamlit reporting app. That implementation status is not a claim that the current revision
has been deployed or that a full live cold/warm qualification run has passed. See
[`docs/SETUP_STATUS.md`](docs/SETUP_STATUS.md) for the evidence boundary.

## Product Boundaries

- The participant performs every target-page click, keystroke, and submit in Browserbase
  interactive Live View.
- The backend may observe sanitized page state, highlight a target, and verify the resulting
  state. It exposes no autonomous Browserbase Agent path.
- Money movement, identity submission, and deletion pause before the irreversible action.
- Replay is deterministic and selector-first. A matching verified replay step creates no
  guidance-model call.
- Passwords are neither requested nor stored.
- Demo and production modes do not fall back to local provider fixtures.

## Architecture

```text
React participant and caregiver UI
                |
                v
FastAPI API, session state, SSE, and transient SQLite outbox
      |                    |                    |
      v                    v                    v
Browserbase          EverOS memory       Snowflake + Cortex
Session + CDP        Case/Skill/Episode  telemetry/cost/guidance
      |
      v
Interactive Live View controlled by the participant

Snowflake product tables and evidence views
                |
                v
Streamlit in Snowflake caregiver evidence app
```

Local development runs the UI and API processes locally. Browser execution still occurs in a
live Browserbase managed session; guidance uses live Snowflake Cortex; durable routine and
completion memory uses live EverOS; telemetry and cost evidence sync to live Snowflake. The
SQLite file is only short-lived operational state and an outbox, not the sponsor evidence or
memory layer.

## Implemented Capabilities

**Participant UI**

- Accessible setup for reading size, voice, and caregiver contact preference.
- Routine chooser backed by EverOS plus a reviewed W3C starter task.
- Embedded Browserbase Live View with one-step guidance, target highlighting, help, dismiss,
  voice output, retry, and stop controls.
- Live session state over authenticated server-sent events.
- Explicit completed, prepared, safety-paused, escalated, failed, and provider-unavailable
  states.

**Caregiver UI**

- Authenticated session history and selected-session detail.
- Snowflake-backed cost-by-run display with explicit empty and unavailable states.
- EverOS routine list and readable skill viewer.
- Persisted escalation notes returned to the active participant session.

**Backend and cloud data**

- Signed participant/caregiver sessions and scoped API access.
- Browserbase create, Live View, server-side CDP attach, sanitized observation, highlight,
  deterministic verification, and explicit termination.
- Rules-based stuck detection, bounded Snowflake Cortex cold/repair guidance, verified route
  recording, selector-first replay, and single-step repair.
- EverOS profile, routine search/read, teach `add`/`flush`, skill retrieval, and episode lookup.
- Consent-gated activity episodes and deterministic daily/weekly/monthly routine timing context.
- Explainable in-app routine reminders with snooze and a required **Start with guidance** permission step.
- SQLite operational event ledger plus retrying Snowflake outbox.
- Idempotent Snowflake `MERGE` writers, actual-usage cost calculator, effective-dated rate
  cards, reconciliation views, evidence queries, and a read-only Streamlit application.

The HTTP surface is documented at `/docs` while the API is running. Core endpoints include
`/health`, `/ready`, participant sessions, task/session lifecycle, Browserbase Live View,
event batches, help/dismiss, SSE, routines, skills, episode answers, escalations, and the
caregiver dashboard.

## Repository Map

```text
backend/app/
  api/                 FastAPI routes
  browser/             CDP observer, sanitizer, highlighter, resolver, verifier
  contracts/           Pydantic runtime contracts
  domain/              safety, state transitions, and skill rules
  integrations/        Browserbase, EverOS, Snowflake, and Cortex adapters
  persistence/         operational SQLite ledger and outbox
  services/            orchestration, guidance, replay, repair, telemetry, cost
web/src/
  setup/               participant setup
  routines/            routine selection
  session/             Live View and guidance experience
  caregiver/           history, costs, notes, and routine evidence
contracts/             portable JSON Schemas
snowflake/
  migrations/          product tables and evidence views
  queries/             drill-through and reconciliation queries
  streamlit/           caregiver evidence app
scripts/               Snowflake deployment and live readiness commands
docs/                  decisions, provider contracts, runbook, and evidence boundary
```

## Local Development

Required tool versions are recorded in [`.tool-versions`](.tool-versions): Node.js 26.5.1,
Python 3.12.11, and pnpm 11.9.0. The container build pins `uv` 0.11.24. Snowflake deployment
also requires the `snow` CLI; Fly deployment requires `flyctl`.

1. Install dependencies and the Playwright Chromium runtime used for CDP attachment:

   ```bash
   cp .env.example .env
   make setup
   ```

2. Populate `.env` with live Browserbase, EverOS, and Snowflake service credentials plus a
   strong `SESSION_SIGNING_SECRET`. Keep `APP_ENV=development`. No local provider substitute is
   started by this repository.

3. Run the backend:

   ```bash
   make backend
   ```

4. In another terminal, run Vite against the local API:

   ```bash
   VITE_API_BASE_URL=http://localhost:8000 pnpm dev
   ```

5. Open `http://localhost:5173`. FastAPI documentation is at
   `http://localhost:8000/docs`.

For a production-shaped local process that serves the built UI and API from one origin:

```bash
pnpm build
PORT=8000 pnpm start
```

Basic process health does not call providers:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

The stricter readiness script requires authorized Browserbase, EverOS, Snowflake, and guidance
capabilities and rejects fixture mode. Browserbase reaches `authorized` only while a
WebAccessible-owned managed session is attached:

```bash
API_PUBLIC_URL=http://localhost:8000 ./scripts/live-readiness.sh
```

## Snowflake Deployment

The Snowflake CLI connection name defaults to `webaccessible`. It must point at the scoped
service role, warehouse, `WEBACCESSIBLE` database, and `APP` schema.

```bash
snow connection test --connection webaccessible
SNOWFLAKE_CONNECTION=webaccessible ./scripts/apply-snowflake.sh
SNOWFLAKE_CONNECTION=webaccessible ./scripts/deploy-streamlit.sh
```

To deploy and open the Streamlit app in one command:

```bash
SNOWFLAKE_CONNECTION=webaccessible OPEN_STREAMLIT=1 ./scripts/deploy-streamlit.sh
```

The migration script applies, in order:

1. `001_session_steps.sql`
2. `002_product_tables.sql`
3. `003_evidence_views.sql`

Published effective rate-card rows must exist in `COST_RATE_CARDS` before an actual cost can be
calculated. The calculator deliberately reports unavailable rather than guessing a missing
rate or treating estimated tokens as actual.

## Fly Deployment

[`fly.toml`](fly.toml) defines the `webaccessible-care` app in `sjc`, one always-running shared
machine, HTTPS, and a persistent `/data` volume for transient operational state. The Docker
image builds the React application and serves it from FastAPI on port 8080.

For a new Fly app, provision the app and volume once:

```bash
flyctl apps create webaccessible-care
flyctl volumes create webaccessible_data --app webaccessible-care --region sjc --size 1
```

With the values exported in the current shell, install the live service secrets:

```bash
flyctl secrets set --app webaccessible-care \
  BROWSERBASE_API_KEY="$BROWSERBASE_API_KEY" \
  EVEROS_API_KEY="$EVEROS_API_KEY" \
  SNOWFLAKE_ACCOUNT="$SNOWFLAKE_ACCOUNT" \
  SNOWFLAKE_USER="$SNOWFLAKE_USER" \
  SNOWFLAKE_PASSWORD="$SNOWFLAKE_PASSWORD" \
  SNOWFLAKE_ROLE="$SNOWFLAKE_ROLE" \
  SNOWFLAKE_WAREHOUSE="$SNOWFLAKE_WAREHOUSE" \
  SNOWFLAKE_DATABASE="$SNOWFLAKE_DATABASE" \
  SNOWFLAKE_SCHEMA="$SNOWFLAKE_SCHEMA" \
  SESSION_SIGNING_SECRET="$(openssl rand -hex 32)" \
  APP_PUBLIC_URL="https://webaccessible-care.fly.dev" \
  API_PUBLIC_URL="https://webaccessible-care.fly.dev"
```

Deploy and inspect the hosted process:

```bash
flyctl deploy --app webaccessible-care
flyctl status --app webaccessible-care
flyctl logs --app webaccessible-care --no-tail
curl -fsS https://webaccessible-care.fly.dev/health
```

During an attached Browserbase task, run the strict provider gate:

```bash
API_PUBLIC_URL=https://webaccessible-care.fly.dev ./scripts/live-readiness.sh
```

Passing that script proves only the current runtime readiness response. Demo readiness still
requires the captured cold teach run, retrievable EverOS objects, warm replay, explicit
Browserbase termination, Snowflake rows, and Streamlit drill-through listed in the demo
runbook and evidence manifest.

## Provider State Labels

`GET /ready` uses these labels independently for each capability:

| Label | Meaning |
|---|---|
| `unconfigured` | Required configuration is absent. |
| `configured` | Required names/secrets are present; no successful live operation is asserted. |
| `reachable` | The provider answered a live request; authorization is not yet asserted. |
| `authorized` | The required scoped live operation succeeded. |
| `unavailable` | A configured provider failed the current live check. |
| `capacity_exhausted` | Browserbase rejected work because the account has no current capacity. |

`ready: true` is a runtime preflight signal, not a substitute for a frozen end-to-end evidence
run. Fixture state, unsynchronized rows, disconnected Streamlit data, or a configured-only
provider cannot support a live sponsor claim.

## Static Checks and Build

The CI workflow runs the same non-provider checks:

```bash
uv sync --frozen --all-groups
pnpm install --frozen-lockfile
uv run ruff check backend
uv run mypy backend
pnpm typecheck
pnpm build
```

## Source Documents

- [`webaccessible-spec.md`](webaccessible-spec.md): canonical product behavior and constraints.
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md): component contracts, work packages, and
  evidence gates.
- [`AGENTS.md`](AGENTS.md): repository operating rules.
- [`SPONSORS.md`](SPONSORS.md) and [`docs/sponsors/`](docs/sponsors/): provider roles and proof
  requirements.
- [`docs/demo-runbook.md`](docs/demo-runbook.md): exact cold/warm qualification sequence.
- [`docs/evidence-manifest.md`](docs/evidence-manifest.md): artifacts required before a demo
  readiness claim.
