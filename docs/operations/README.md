# WebAccessible Operations

Production operations tooling for the hosted WebAccessible deployment. Nothing
in `ops/` or in these runbooks changes application behaviour: every check is
read-only, and every recovery command is an operator action that must be run
deliberately.

- Checks live in [`ops/`](../../ops).
- Incident procedures live in this directory.
- Provider evidence and the remaining live gates live in
  [`docs/SETUP_STATUS.md`](../SETUP_STATUS.md), which stays the source of truth
  for what has and has not been qualified.

## Status vocabulary

Every check resolves to exactly one of five states. They are ordered by how much
evidence the check actually collected, not by how the result feels.

| State | Meaning | Exit code |
|---|---|---|
| `verified` | Every assertion the check names was satisfied against the live provider. | 0 |
| `healthy` | A live read-only provider call succeeded, but at least one assertion was skipped or unmet. | 10 |
| `degraded` | A live call was attempted; the provider is reachable or configured, but the observed state is impaired, partial, or past a documented limit. | 20 |
| `configured` | Configuration is present. No live call was attempted or completed, so nothing about the provider itself is asserted. | 30 |
| `unconfigured` | Required configuration is absent. No provider call was possible. | 40 |

Two additional exit codes are not states: `2` is a usage error, and `127` means a
required CLI is missing.

`verified` is always scoped to the narrow assertion the check names. **No check
in this repository verifies end-to-end product readiness.** Every check prints a
"Not proven by this check" block, and those boundaries are the honest limit of
what its output may be quoted for.

### Relationship to the application's `/ready` vocabulary

The hosted application reports a different, provider-facing vocabulary
(`unconfigured`, `configured`, `reachable`, `authorized`, `unavailable`,
`capacity_exhausted`) documented in [`docs/SETUP_STATUS.md`](../SETUP_STATUS.md).
The ops vocabulary describes *a check run by an operator*; the app vocabulary
describes *a capability inside the running process*. They are related but not
interchangeable:

| App capability state | Typical ops state for the matching check |
|---|---|
| `unconfigured` | `unconfigured` |
| `configured` | `configured` or `healthy`, depending on whether the check made a live read |
| `reachable` / `authorized` | `healthy`, and `verified` when the check's full assertion also passed |
| `unavailable` | `degraded` |
| `capacity_exhausted` | `degraded` |

## Checks

| Check | Command | Asserts |
|---|---|---|
| Fly deployment | `ops/verify-fly-deployment.sh` | The live hosted HTTPS URL serves the expected app from a started Fly machine on a readable release. |
| Snowflake schema | `ops/verify-snowflake-schema.sh` | Every table and view in `snowflake/migrations/*.sql` exists and compiles for the named connection's role. |
| EverOS readiness | `uv run ops/verify-everos-readiness.py` | The EverOS read path answers for the configured memory scope. Non-mutating. |
| Browserbase inventory | `uv run ops/verify-browserbase-inventory.py` | Account, project usage, and active-session inventory, with orphan and headroom detection. Creates nothing. |

Shared behaviour lives in [`ops/lib/`](../../ops/lib):

- `ops_redact.py` is the single redaction implementation. Run
  `python3 ops/lib/ops_redact.py --self-test` to confirm it still strips
  credentials and capability URLs; it touches no provider and no network.
- `ops_status.py` and `ops_status.sh` define the vocabulary, exit codes, and
  loopback refusal used by the Python and Bash checks respectively.

## Recommended execution order

Run in dependency order. Each step's evidence is a precondition for the next
step's evidence being meaningful.

```bash
# 0. Confirm the redaction filter still holds. No network, no provider.
python3 ops/lib/ops_redact.py --self-test

# 1. Data plane. Nothing downstream is trustworthy if the schema is incomplete.
SNOWFLAKE_CONNECTION=webaccessible ./ops/verify-snowflake-schema.sh

# 2. Memory plane. Read-only; safe to run at any time.
uv run ops/verify-everos-readiness.py

# 3. Browser capacity. Confirms a session can be started before anyone tries.
uv run ops/verify-browserbase-inventory.py

# 4. Hosted deployment, last, because it reports the other three back through /ready.
FLY_APP=webaccessible-care ./ops/verify-fly-deployment.sh https://webaccessible-care.fly.dev
```

Stop at the first `degraded` result and open the matching runbook. A `degraded`
data plane makes a `verified` deployment misleading, not reassuring.

## What running all four checks does not establish

Four `verified` results still do not mean the product is demo-ready. In
particular they do not prove:

- a WebAccessible-owned Browserbase cold teach session that was created,
  attached, driven by trusted participant input, and explicitly terminated;
- an EverOS teach write, flush, and post-indexing readback of the exact skill
  revision used for replay;
- a backend-created, non-fixture row in `SESSION_RUNS`, `SESSION_STEPS`,
  `MODEL_CALLS`, and `MODEL_COSTS`;
- one real Cortex guidance call with actual usage and a retained query ID;
- a Streamlit drill-through against that specific run.

Those are the live gates enumerated in
[`docs/SETUP_STATUS.md`](../SETUP_STATUS.md). Until they have evidence, the
accurate status remains **implemented, not live-qualified or demo-ready**.

## Runbooks

| Situation | Runbook |
|---|---|
| Browserbase concurrency exhausted or orphaned sessions billing | [runbook-browserbase-exhaustion.md](runbook-browserbase-exhaustion.md) |
| EverOS Case written but Skill not yet retrievable | [runbook-everos-indexing-delay.md](runbook-everos-indexing-delay.md) |
| Telemetry outbox not draining into Snowflake | [runbook-snowflake-outbox-backlog.md](runbook-snowflake-outbox-backlog.md) |
| Fly app unhealthy, stopped, or serving the wrong revision | [runbook-fly-restart.md](runbook-fly-restart.md) |
| Streamlit entity failed to deploy or shows no data | [runbook-streamlit-deploy-failure.md](runbook-streamlit-deploy-failure.md) |

## Standing constraints for every operator action

These apply to every command in every runbook.

**Never run, in any recovery path:**

- Destructive Git: `git reset --hard`, `git checkout -- .`, `git clean -fd`,
  `git push --force`, branch or tag deletion. Roll a deployment back by
  redeploying a known image, never by rewriting history.
- Provider-wide deletion: `flyctl apps destroy`, `flyctl volumes destroy`,
  `DROP DATABASE`, `DROP SCHEMA`, `snow object drop`, EverOS memory-space
  deletion, or any bulk Browserbase session termination.
- Anything that terminates a Browserbase session another operator or participant
  is currently using. Reclaim one identified session at a time.

**Never do, when reporting:**

- Paste a Browserbase CDP URL, Live View URL, API key, Snowflake password or
  token, or any signed URL into a ticket, screenshot, log, or evidence manifest.
  Pipe command output through `python3 ops/lib/ops_redact.py` first.
- Substitute a fixture, local service, or `localhost` endpoint for a cloud
  provider. The checks refuse loopback endpoints for this reason.
- Quote a green `/health` or `/ready` as end-to-end readiness.
- Record a Browserbase session as stopped without provider-confirmed
  termination. A failed termination is `termination_pending`, not stopped.
