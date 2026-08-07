# Runbook: Snowflake outbox backlog

The click loop writes an accepted transition and an outbox record in one
operational transaction, then updates the participant UI without waiting on the
warehouse. A background synchronizer drains `telemetry_outbox` from the
operational SQLite database on the Fly volume into Snowflake using idempotent
`MERGE`s keyed by stable IDs. When that drain stalls, rows exist locally but not
in the warehouse, and the cost curve and sponsor claims must exclude them.

**Owner:** operator on duty. **Blast radius:** evidence and reporting. Guidance
and participant flow keep working; the run is visibly unsynced.

## 1. Trigger

Any of:

- `./ops/verify-snowflake-schema.sh` reports `degraded`, or `snow connection test`
  fails.
- The hosted `/ready` reports the `snowflake` capability as `unavailable`.
- `V_PROVIDER_SYNC_STATUS` shows non-zero `ingestion_pending_count` or
  `ingestion_failed_count` for a finished run.
- A caregiver view or the Streamlit app shows "No verified data" for a run that
  the participant completed.

## 2. Assess

Work outward from the warehouse, then inward to the machine.

```bash
# 2a. Is the schema itself intact and readable? Read-only.
SNOWFLAKE_CONNECTION=webaccessible ./ops/verify-snowflake-schema.sh
```

```bash
# 2b. What does the warehouse think the sync status is? Read-only.
snow sql --connection webaccessible --format JSON \
  --filename snowflake/queries/provider_sync_status.sql \
  | python3 ops/lib/ops_redact.py
```

```bash
# 2c. Duplicates, gaps, and incomplete sessions. Read-only.
snow sql --connection webaccessible --format JSON \
  --filename snowflake/queries/reconciliation.sql \
  | python3 ops/lib/ops_redact.py
```

```bash
# 2d. What is actually queued on the machine? Read-only: the database is opened
#     with mode=ro so this cannot lock or modify the operational store.
flyctl ssh console --app webaccessible-care --command \
  "python3 -c \"import sqlite3; c=sqlite3.connect('file:/data/webaccessible.sqlite3?mode=ro', uri=True); print(list(c.execute('SELECT status, COUNT(*), MAX(attempts) FROM telemetry_outbox GROUP BY status')))\""
```

```bash
# 2e. Why is it failing? Error codes only. `payload_json` is never selected.
flyctl ssh console --app webaccessible-care --command \
  "python3 -c \"import sqlite3; c=sqlite3.connect('file:/data/webaccessible.sqlite3?mode=ro', uri=True); print(list(c.execute('SELECT kind, last_error_code, COUNT(*) FROM telemetry_outbox WHERE status = ? GROUP BY kind, last_error_code', ('failed',))))\""
```

Classify:

| Observation | State | Meaning |
|---|---|---|
| Named connection missing from the CLI store | `unconfigured` | No live statement ran. |
| Connection defined, `snow connection test` fails | `configured` | Credentials or network. No schema state observed. |
| Connected, tables or views missing | `degraded` | Migrations were not applied. See §4a. |
| Connected and complete, outbox rows `pending` and rising | `degraded` | The drain is stalled. See §4b. |
| Connected and complete, outbox rows `failed` with a repeating `last_error_code` | `degraded` | A payload or permission problem. See §4c. |
| Connected, complete, views readable, outbox drained | `verified` | Schema and drain are both healthy. |

## 3. Contain

- Mark the affected runs unsynced and keep them out of every claim. Unsynced rows
  never power the cost chart or a sponsor statement.
- Do **not** start a demo. Demo mode must refuse to begin the sponsor proof while
  Snowflake is unavailable.
- Do **not** backfill from `ACCOUNT_USAGE`. It is reconciliation and backfill
  only, never the live cost source. A missing product row shows `unavailable`.
- Do **not** hand-insert rows to make a chart render. The stable event and call
  IDs are what make the `MERGE` idempotent; a hand-written row breaks
  reconciliation.
- Do **not** delete outbox rows to clear the backlog. They are the only durable
  record that the transition happened.

## 4. Recover

### 4a. The schema is incomplete

Migrations are additive and safe to re-apply; `apply-snowflake.sh` runs them in
order and every statement is `CREATE TABLE IF NOT EXISTS`, an additive `ALTER`,
`CREATE OR REPLACE VIEW`, or a keyed `MERGE`.

```bash
snow connection test --connection webaccessible
SNOWFLAKE_CONNECTION=webaccessible ./scripts/apply-snowflake.sh
SNOWFLAKE_CONNECTION=webaccessible ./ops/verify-snowflake-schema.sh
```

### 4b. The drain is stalled but rows are only `pending`

The synchronizer retries with bounded exponential backoff and stable IDs, so the
first action is to give it a bounded window and re-measure rather than
intervening.

```bash
# Watch the queue drain. Read-only; repeat three times, 60 seconds apart.
for attempt in 1 2 3; do
  flyctl ssh console --app webaccessible-care --command \
    "python3 -c \"import sqlite3; c=sqlite3.connect('file:/data/webaccessible.sqlite3?mode=ro', uri=True); print(list(c.execute('SELECT status, COUNT(*) FROM telemetry_outbox GROUP BY status')))\""
  sleep 60
done
```

If the `pending` count is falling, do nothing further. If it is flat across all
three readings, the synchronizer task is not running. Restart the machine to
restart the task; the outbox is durable on the mounted volume and survives:

```bash
flyctl machine list --app webaccessible-care
flyctl machine restart "$MACHINE_ID" --app webaccessible-care
flyctl status --app webaccessible-care
```

Then re-measure with the loop above. Restart is safe because the `MERGE` is keyed
by stable event and call IDs: replaying a batch cannot double-count.

### 4c. Rows are `failed` with a repeating error code

Read the code before retrying. Retrying a permission error a fourth time changes
nothing.

| `last_error_code` pattern | Action |
|---|---|
| Authentication or role errors | The service credential or role grant changed. Fix the grant in Snowflake, then §4d. |
| Warehouse suspended or unavailable | Confirm `WEBACCESSIBLE_WH` is resumable for the role, then §4d. |
| `invalid_outbox_item` | The payload does not match the current schema. Apply migrations (§4a) first; these rows retry cleanly once the column exists. |
| Timeouts | Usually transient. Follow §4b. |

### 4d. Force one bounded retry pass

Retry is driven by the application, not by hand-editing the queue. A restart
re-enters the drain loop and re-selects rows whose status is `pending` or
`failed`:

```bash
flyctl machine restart "$MACHINE_ID" --app webaccessible-care
```

Confirm the pass ran, then check the warehouse side:

```bash
snow sql --connection webaccessible --format JSON \
  --filename snowflake/queries/reconciliation.sql \
  | python3 ops/lib/ops_redact.py
```

## 5. Rollback

Migrations are additive, so there is no schema rollback to perform and none to
attempt. If a Snowflake secret was changed while diagnosing, restore the previous
values and let the app restart:

```bash
# Restore the service identity documented in .env.example.
flyctl secrets set --app webaccessible-care \
  SNOWFLAKE_ROLE=WEBACCESSIBLE_APP_ROLE \
  SNOWFLAKE_WAREHOUSE=WEBACCESSIBLE_WH \
  SNOWFLAKE_DATABASE=WEBACCESSIBLE \
  SNOWFLAKE_SCHEMA=APP
flyctl status --app webaccessible-care
```

If a bad application revision caused the backlog, roll the deployment back rather
than the data. See [runbook-fly-restart.md](runbook-fly-restart.md) §5.

## 6. Verify

```bash
SNOWFLAKE_CONNECTION=webaccessible ./ops/verify-snowflake-schema.sh
```

```bash
# Zero pending and zero failed for the affected run.
snow sql --connection webaccessible --format JSON \
  --filename snowflake/queries/provider_sync_status.sql \
  | python3 ops/lib/ops_redact.py
```

Recovery is complete when the schema check reports `verified`, the outbox reports
no `pending` or `failed` rows, and `V_PROVIDER_SYNC_STATUS` shows
`ingestion_pending_count` and `ingestion_failed_count` at zero for the run.

## 7. What this runbook does not prove

- A drained outbox proves rows reached the warehouse. It does not prove the rows
  are complete, correct, or drillable end to end. Run
  `snowflake/queries/cost_lineage.sql` and
  `snowflake/queries/replay_invariant.sql` for that.
- A `verified` schema check proves the migrations ran. It does not prove any
  backend-created, non-fixture row exists.
- Present rows do not prove cost. Cost requires the effective `COST_RATE_CARDS`
  row for the exact model and timestamp; a missing or stale rate card must render
  cost `unavailable`, never guessed.
- Nothing here proves a Cortex call was made. That is a separate live gate.

## 8. Prohibited in this runbook

- `DROP TABLE`, `DROP VIEW`, `DROP SCHEMA`, `DROP DATABASE`, `TRUNCATE`, or
  `snow object drop` against `WEBACCESSIBLE.APP`.
- Deleting, editing, or re-keying rows in `telemetry_outbox`.
- Inserting rows into Snowflake by hand to make a view or chart populate.
- Reading cost or usage from `ACCOUNT_USAGE` and presenting it as the live cost.
- Opening the operational SQLite database read-write over SSH.
- Pasting the Snowflake password, token, or full account identifier into a
  ticket. Pipe output through `python3 ops/lib/ops_redact.py`.
