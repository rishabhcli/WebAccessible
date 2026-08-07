# Runbook: Fly restart and deployment rollback

`fly.toml` defines the `webaccessible-care` app in `sjc` with one always-running
shared-CPU machine, `force_https`, and a persistent `webaccessible_data` volume
mounted at `/data`. That volume holds the operational SQLite database, including
the durable telemetry outbox, so restarts are safe but machine replacement is
not something to do casually.

**Owner:** operator on duty. **Blast radius:** the entire hosted participant and
caregiver experience.

## 1. Trigger

Any of:

- `./ops/verify-fly-deployment.sh` reports `degraded` or `configured`.
- The hosted URL returns 5xx, times out, or serves no application shell.
- `flyctl status` shows no machine in the `app` process group in state `started`.
- The deployed revision is not the one you expect.

## 2. Assess

```bash
# Read-only. Combines platform state with live hosted evidence.
FLY_APP=webaccessible-care ./ops/verify-fly-deployment.sh https://webaccessible-care.fly.dev
```

```bash
# Platform detail, read-only.
flyctl status --app webaccessible-care
flyctl machine list --app webaccessible-care
flyctl releases --app webaccessible-care --image
flyctl logs --app webaccessible-care --no-tail | python3 ops/lib/ops_redact.py
```

Classify:

| Observation | State | Meaning |
|---|---|---|
| No app name or hosted URL resolved | `unconfigured` | Nothing was checked. |
| URL set, nothing answered, no machine evidence | `configured` | The app may never have deployed. See §4a. |
| Machines exist, URL silent | `degraded` | Process crash-loop or port mismatch. See §4b. |
| URL answers, `/health` or `/ready` wrong | `degraded` | The process is up but impaired. See §4c. |
| Endpoints correct, platform evidence missing | `healthy` | Run with `flyctl` authenticated to reach `verified`. |
| Endpoints correct plus started machine and readable release | `verified` | The deployment is serving the expected revision. |

Note the expected `/ready` shape before calling anything a fault: with no
participant session attached, the `browserbase` capability reporting `configured`
rather than `authorized` is correct, not degraded.

## 3. Contain

- Announce the outage. Do not let a participant start a task against an impaired
  deployment.
- Do **not** run a demo or record evidence from a deployment in this state.
- Do **not** point anyone at a local development server as a stand-in. A local
  service is never a substitute for the hosted deployment.
- Do **not** destroy or recreate the machine as a first response. Machine
  destruction risks the `/data` volume attachment and the durable outbox with it.

## 4. Recover

Escalate through these in order. Stop at the first one that restores service.

### 4a. Nothing is deployed

Confirm the app and volume exist before deploying:

```bash
flyctl status --app webaccessible-care
flyctl volumes list --app webaccessible-care
flyctl secrets list --app webaccessible-care
```

`flyctl secrets list` prints names and digests, never values. If the app, volume,
and secrets are present but no release exists, deploy the current revision:

```bash
pnpm build
flyctl deploy --app webaccessible-care
flyctl status --app webaccessible-care
```

### 4b. Machines exist but the URL is silent

Restart one machine first. The volume, and therefore the outbox, persists.

```bash
flyctl machine list --app webaccessible-care
flyctl machine restart "$MACHINE_ID" --app webaccessible-care
flyctl status --app webaccessible-care
```

Re-check the hosted URL:

```bash
FLY_APP=webaccessible-care ./ops/verify-fly-deployment.sh https://webaccessible-care.fly.dev
```

If a single machine restart does not help, restart the app:

```bash
flyctl apps restart webaccessible-care
flyctl status --app webaccessible-care
```

If the process is crash-looping, read why before restarting a third time:

```bash
flyctl logs --app webaccessible-care --no-tail --machine "$MACHINE_ID" \
  | python3 ops/lib/ops_redact.py
```

A machine that is `stopped` rather than crash-looping may simply have been
auto-stopped. `auto_start_machines` is on, so a request should start it; if it
does not, start it explicitly:

```bash
flyctl machine start "$MACHINE_ID" --app webaccessible-care
```

### 4c. The URL answers but the process is impaired

Read which capability is wrong, then use that provider's runbook. The deployment
is usually not the fault:

| `/ready` symptom | Runbook |
|---|---|
| `snowflake` or `guidance_model` unavailable | [runbook-snowflake-outbox-backlog.md](runbook-snowflake-outbox-backlog.md) |
| `everos` unavailable | [runbook-everos-indexing-delay.md](runbook-everos-indexing-delay.md) §4b |
| `browserbase` `capacity_exhausted` | [runbook-browserbase-exhaustion.md](runbook-browserbase-exhaustion.md) |
| `fixture_mode` is true | The wrong `APP_ENV` is deployed. See §5. |

A missing or wrong secret is the other common cause. Confirm names, then re-set
only the one that is wrong:

```bash
flyctl secrets list --app webaccessible-care
flyctl secrets set --app webaccessible-care APP_ENV=production
```

Setting a secret triggers a restart. Re-verify afterwards.

## 5. Rollback

Roll back by redeploying a known-good image. Never by rewriting Git history.

```bash
# 1. List releases with their image references. Read-only.
flyctl releases --app webaccessible-care --image

# 2. Read the currently deployed image so you can return to it if needed.
flyctl image show --app webaccessible-care --json | python3 ops/lib/ops_redact.py

# 3. Redeploy the previous known-good image reference verbatim.
flyctl deploy --app webaccessible-care --image "$PREVIOUS_IMAGE_REF"

# 4. Confirm the rollback landed and pin the expectation.
flyctl status --app webaccessible-care
OPS_EXPECT_IMAGE="$PREVIOUS_IMAGE_REF" FLY_APP=webaccessible-care \
  ./ops/verify-fly-deployment.sh https://webaccessible-care.fly.dev
```

Step 4 is the point of the rollback: `verify-fly-deployment.sh` reports
`degraded` if the deployed image does not contain `OPS_EXPECT_IMAGE`, so a
rollback that silently did not take cannot be mistaken for success.

To roll forward again, redeploy the newer image reference the same way.

## 6. Verify

```bash
OPS_EXPECT_IMAGE="$EXPECTED_IMAGE_REF" FLY_APP=webaccessible-care \
  ./ops/verify-fly-deployment.sh https://webaccessible-care.fly.dev
```

Recovery is complete when the check reports `verified`: `/health` is ok, the web
bundle is served, `/ready` is true with no fixture mode, and at least one `app`
machine is `started` on a readable release matching the expected image.

## 7. What this runbook does not prove

- A `verified` deployment proves the process answers and serves the expected
  revision. It does not prove any provider round trip: no Browserbase create,
  attach, or terminate; no EverOS write and readback; no backend-created
  Snowflake row; no Cortex call.
- A green `/health` and `/ready` is not demo readiness, and must never be quoted
  as such. The remaining live gates are in
  [`docs/SETUP_STATUS.md`](../SETUP_STATUS.md).
- A successful restart does not prove the outbox drained. Confirm that
  separately with
  [runbook-snowflake-outbox-backlog.md](runbook-snowflake-outbox-backlog.md) §6.
- Nothing here proves the deployment would survive the next restart.

## 8. Prohibited in this runbook

- `flyctl apps destroy`, `flyctl volumes destroy`, `flyctl machine destroy`, or
  `flyctl machine kill` as a recovery step. Destroying the machine risks the
  `/data` volume and the durable outbox on it.
- `git reset --hard`, `git checkout -- .`, `git clean -fd`, `git push --force`,
  or deleting any branch or tag to "roll back". Roll back by redeploying an
  image.
- Deploying an untested local working tree to production during an incident.
  Redeploy a known image reference instead.
- Editing `fly.toml`, the `Dockerfile`, or any application file to work around an
  incident. Both are outside operational ownership.
- Putting a secret value into `fly.toml`, a ticket, or a log. Secrets are
  installed only with `flyctl secrets set`, and `flyctl secrets list` shows names
  and digests only.
- Reporting the app healthy on the strength of `flyctl status` alone. Platform
  state and hosted evidence are separate; the check requires both.
