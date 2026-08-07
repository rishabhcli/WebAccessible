# Runbook: Failed Streamlit deployment

The caregiver reporting surface is a read-only Streamlit entity inside Snowflake,
declared in `snowflake/snowflake.yml` as `WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER`
and deployed by `scripts/deploy-streamlit.sh`. It reads the evidence views only;
it owns no product data. A failed deployment therefore never risks the data,
only the ability to see it.

**Owner:** operator on duty. **Blast radius:** caregiver reporting and evidence
drill-through. Participant flow is unaffected.

## 1. Trigger

Any of:

- `./scripts/deploy-streamlit.sh` exits non-zero.
- `./ops/verify-snowflake-schema.sh` warns that `streamlit_entities` is `0`.
- `snow streamlit get-url` fails or returns a URL that does not open.
- The app opens but every panel reports no data.

## 2. Assess

Separate the four failure classes before touching anything.

```bash
# 2a. Does the connection work at all? Read-only.
snow connection test --connection webaccessible
```

```bash
# 2b. Is the schema the app reads actually complete? Read-only.
SNOWFLAKE_CONNECTION=webaccessible ./ops/verify-snowflake-schema.sh
```

```bash
# 2c. Does the entity exist, and can its URL be resolved? Read-only.
snow sql --connection webaccessible --format JSON \
  --query "SHOW STREAMLITS IN SCHEMA WEBACCESSIBLE.APP;" \
  | python3 ops/lib/ops_redact.py

snow streamlit get-url WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER \
  --connection webaccessible | python3 ops/lib/ops_redact.py
```

```bash
# 2d. Does the role hold the grants the entity needs? Read-only.
snow sql --connection webaccessible --format JSON \
  --query "SHOW GRANTS TO ROLE WEBACCESSIBLE_APP_ROLE;" \
  | python3 ops/lib/ops_redact.py
```

Classify:

| Observation | State | Meaning |
|---|---|---|
| Named connection missing from the CLI store | `unconfigured` | Nothing was deployed or checked. |
| Connection defined, `snow connection test` fails | `configured` | Credentials or network. Fix before deploying. |
| Connected, tables or views missing | `degraded` | Deploying now produces an app that cannot query. See §4a. |
| Connected and complete, no Streamlit entity | `degraded` | The deploy never landed. See §4b. |
| Entity exists, app renders, every panel empty | `degraded` | Not a deployment failure. See §4d. |
| Entity exists, URL resolves, schema `verified` | `verified` | The reporting surface is deployed against a complete schema. |

## 3. Contain

- Do **not** present the caregiver view or any screenshot of it as evidence while
  this is unresolved.
- Do **not** add sample, seeded, or placeholder metrics to make a panel render.
  An empty query must report "No verified data", never a sample metric.
- Do **not** grant the role broader privileges than the entity needs to force a
  deploy through. The entity is read-only by design.
- Do **not** drop and recreate the schema. Streamlit deployment failures are
  never a data problem.

## 4. Recover

### 4a. The schema is incomplete

The Streamlit app queries the evidence views. Deploying it against a partial
schema produces an app that fails at runtime instead of at deploy time. Fix the
schema first:

```bash
snow connection test --connection webaccessible
SNOWFLAKE_CONNECTION=webaccessible ./scripts/apply-snowflake.sh
SNOWFLAKE_CONNECTION=webaccessible ./ops/verify-snowflake-schema.sh
```

Proceed only when the schema check reports `verified`.

### 4b. Retry the deployment

`deploy-streamlit.sh` already passes `--replace`, so re-running it is the retry.
It replaces the entity definition in place; it does not drop the schema, the
views, or any product table.

```bash
SNOWFLAKE_CONNECTION=webaccessible ./scripts/deploy-streamlit.sh
```

If that fails, run the underlying command directly to see the full error:

```bash
snow streamlit deploy webaccessible_caregiver \
  --project snowflake \
  --connection webaccessible \
  --replace \
  --prune
```

Common causes, in the order they usually occur:

| Symptom | Cause | Action |
|---|---|---|
| Stage error on `WEBACCESSIBLE_STREAMLIT_STAGE` | The stage does not exist or the role cannot write to it | Grant the role `CREATE STAGE` on `WEBACCESSIBLE.APP`, then retry |
| Artifact not found | A file listed in `snowflake/snowflake.yml` is missing from the checkout | Restore the checkout; do not edit the entity definition |
| Warehouse error | `WEBACCESSIBLE_WH` is suspended or not granted | Confirm usage on the warehouse for the role, then retry |
| Object already exists | A partial previous deploy | `--replace` is already set; retry once more |

### 4c. Confirm the entity resolves

```bash
snow streamlit get-url WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER \
  --connection webaccessible | python3 ops/lib/ops_redact.py
```

Open it manually. `OPEN_STREAMLIT=1 ./scripts/deploy-streamlit.sh` opens it
automatically if you prefer.

### 4d. The app deployed but every panel is empty

This is the expected, correct behaviour when no verified run exists. It is not a
deployment failure and must not be treated as one.

```bash
# Is there any verified run at all? Read-only.
snow sql --connection webaccessible --format JSON \
  --filename snowflake/queries/latest_verified_session.sql \
  | python3 ops/lib/ops_redact.py
```

If that returns no row, the correct action is to complete a real run, not to
change the app. If it returns a row but the panel is still empty, check that the
run synced: see
[runbook-snowflake-outbox-backlog.md](runbook-snowflake-outbox-backlog.md).

## 5. Rollback

The entity is a read-only view over data it does not own, so rollback means
restoring the previous entity definition, never removing data.

```bash
# 1. Confirm what is deployed now. Read-only.
snow sql --connection webaccessible --format JSON \
  --query "SHOW STREAMLITS IN SCHEMA WEBACCESSIBLE.APP;" \
  | python3 ops/lib/ops_redact.py

# 2. Check out the previous known-good revision of the entity into a worktree,
#    leaving your current checkout untouched. No history is rewritten.
git worktree add ../webaccessible-streamlit-rollback "$PREVIOUS_GOOD_COMMIT"

# 3. Redeploy from that worktree. --replace restores the prior definition.
snow streamlit deploy webaccessible_caregiver \
  --project ../webaccessible-streamlit-rollback/snowflake \
  --connection webaccessible \
  --replace \
  --prune

# 4. Verify, then remove the temporary worktree.
snow streamlit get-url WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER \
  --connection webaccessible | python3 ops/lib/ops_redact.py
git worktree remove ../webaccessible-streamlit-rollback
```

A worktree is used deliberately: it reaches an older revision without
`git checkout`, `git reset`, or `git stash` touching the working tree an incident
responder may still need.

## 6. Verify

```bash
SNOWFLAKE_CONNECTION=webaccessible ./ops/verify-snowflake-schema.sh
```

Recovery is complete when the check reports `verified` and `streamlit_entities`
is at least `1`, and `snow streamlit get-url` resolves.

## 7. What this runbook does not prove

- A deployed Streamlit entity proves the reporting surface exists. It does not
  prove any verified run is visible in it.
- A rendering panel is not evidence unless it drills through
  `SESSION_RUNS -> SESSION_STEPS -> MODEL_CALLS -> MODEL_COSTS -> COST_RATE_CARDS`
  for one specific run.
- A cost figure shown here is only as good as the effective rate-card row behind
  it. A missing or stale rate card must render cost `unavailable`, never guessed.
- Deploying the entity is a separate live gate from a Cortex call, an EverOS
  readback, or a Browserbase lifecycle. See
  [`docs/SETUP_STATUS.md`](../SETUP_STATUS.md).

## 8. Prohibited in this runbook

- `DROP STREAMLIT`, `DROP SCHEMA`, `DROP DATABASE`, or `snow object drop` against
  `WEBACCESSIBLE.APP`. `--replace` is the supported redeploy path.
- `git reset --hard`, `git checkout -- .`, `git clean -fd`, `git push --force`,
  or branch deletion to reach an older revision. Use a worktree, as in §5.
- Granting the role write privileges on product tables to make a deploy succeed.
- Seeding, mocking, or hard-coding sample metrics into the Streamlit app.
- Editing `snowflake/streamlit/streamlit_app.py`, `snowflake/snowflake.yml`, or
  any migration during an incident. They are outside operational ownership.
- Pasting the resolved Streamlit URL with its query string, the account
  identifier, or any credential into a ticket. Pipe output through
  `python3 ops/lib/ops_redact.py`.
