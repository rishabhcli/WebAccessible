# Runbook: EverOS indexing delay

After a teach run calls `add` and `flush`, EverOS needs time to extract and index
the Case, Skill, and Episode. During that window a search will not find the skill
even though the write succeeded. The application already models this as an
`indexing` state and retries direct retrieval on a bounded schedule
(`0, 1, 2, 4, 8` seconds). This runbook covers the case where the window does not
close.

**Owner:** operator on duty. **Blast radius:** warm replay and skill claims for
one user. Cold guidance and safety rules are unaffected.

## 1. Trigger

Any of:

- `uv run ops/verify-everos-readiness.py --session-id <ID>` reports `degraded`
  with "A Case for this session is visible but no Skill is."
- A teach run returned `indexing_status: indexing` rather than `ready`.
- The caregiver skill viewer shows a routine that cannot be opened for replay.
- The hosted `/ready` reports the `everos` capability as `unavailable`.

## 2. Assess

```bash
# Read-only. Safe during an incident and safe to repeat.
uv run ops/verify-everos-readiness.py --session-id "$SESSION_ID"
```

The check reports three visibility flags for the session:

| Field | Reading |
|---|---|
| `session.agent_case_visible` | Extraction produced a Case. The write landed. |
| `session.agent_skill_visible` | The Skill is retrievable. Replay can load it. |
| `session.episode_visible` | The user-scope Episode is retrievable. |

Classify:

| Observation | State | Meaning |
|---|---|---|
| `EVEROS_API_KEY` absent | `unconfigured` | Nothing was checked. |
| Key present, SDK unavailable | `configured` | Run under `uv run` from the repo root. |
| Case visible, Skill not | `degraded` | Indexing is in flight. This runbook applies. |
| No Case visible at all | `degraded` | Not indexing lag. The `flush` did not produce a Case; see §4c. |
| Agent read succeeds, search skipped or slow | `healthy` | The read path answers; the full assertion was not met. |
| Agent read, user read, and search all succeed | `verified` | The read path is proven. Any missing skill is a write problem, not a read problem. |

Record the elapsed time since `flush`. The documented index window is roughly
10–15 seconds; a delay past two minutes is not normal lag.

## 3. Contain

- Do **not** re-run `add` or `flush` for the same session. Both are extraction
  triggers; repeating them risks duplicate Cases with no way to select the right
  one for replay.
- Do **not** claim a Skill exists. Until the Skill is retrievable, the truthful
  state is `indexing`, and the run must not be presented as replayable.
- Do **not** substitute a golden fixture skill for the missing one. A fixture is
  not evidence, and `fixture_mode` is forbidden in demo and production.
- Warm replay for this task stays unavailable. Cold guidance still works and is
  the correct fallback to offer.

## 4. Recover

### 4a. Wait out the index window, then re-read by known ID

The only correct first action is bounded waiting with direct retrieval. Do not
depend on search during the window.

```bash
# Poll the read path four times over two minutes. Nothing is written.
for attempt in 1 2 3 4; do
  echo "attempt $attempt"
  uv run ops/verify-everos-readiness.py --session-id "$SESSION_ID" --skip-search \
    && break
  sleep 30
done
```

`--skip-search` is deliberate here: search is the slowest surface to become
consistent, and its absence is not what you are waiting on.

### 4b. Confirm the read path itself is not the problem

If the Skill is still invisible after two minutes, separate "not indexed yet"
from "cannot read":

```bash
# Full read-path probe, including hybrid search, against the agent scope.
uv run ops/verify-everos-readiness.py --json | python3 -m json.tool
```

- `verified` means reads work and the Skill genuinely is not there yet.
- `degraded` with failed probes means EverOS is unauthorized, unreachable, or
  returning an unusable envelope. That is a provider incident, not index lag;
  escalate and stop retrying.

### 4c. No Case was produced at all

A missing Case means `flush` did not complete extraction. The correct state is
`add` succeeded, `flush` did not, and no Skill claim may be made.

Retry the teach persistence exactly once, from the application, for that session.
Do not call the SDK by hand:

```bash
# Confirm the run's current provider status before retrying anything.
SNOWFLAKE_CONNECTION=webaccessible snow sql --connection webaccessible --format JSON \
  --query "SELECT run_id, everos_provider_status, everos_indexing_status, everos_skill_id
           FROM WEBACCESSIBLE.APP.V_PROVIDER_SYNC_STATUS
           WHERE run_id = '$RUN_ID';" \
  | python3 ops/lib/ops_redact.py
```

If `everos_provider_status` shows the write failed, the run is not teachable and
the participant must repeat the task. That is a product outcome, not an ops
workaround.

## 5. Rollback

There is nothing to roll back: this runbook performs no EverOS write.

If an EverOS configuration value was changed while diagnosing, restore it and
restart the app:

```bash
# Restore the documented defaults from backend/app/config.py.
flyctl secrets set --app webaccessible-care \
  EVEROS_APP_ID=default \
  EVEROS_PROJECT_ID=default \
  EVEROS_TIMEOUT_SECONDS=60
flyctl status --app webaccessible-care
```

Do not attempt to "roll back" a Skill by deleting memory. The installed SDK
exposes no safe selective agent-skill deletion, and the adapter deliberately
refuses to emulate one; a repair produces a new revision that preserves
`source_case_id` and the old revision's linkage.

## 6. Verify

```bash
uv run ops/verify-everos-readiness.py --session-id "$SESSION_ID"
```

Recovery is complete when `session.agent_skill_visible` is true and the check
reports `healthy` or `verified`.

## 7. What this runbook does not prove

- A visible Skill is not a valid Skill. Replay additionally requires the skill
  document to validate against `contracts/skill.schema.json` and to carry the
  exact revision the run recorded.
- A `verified` read path does not prove the write path. `add`, `flush`, and
  post-indexing readback of a real teach run remain a separate live gate in
  [`docs/SETUP_STATUS.md`](../SETUP_STATUS.md).
- Retrieving a Skill by ID does not prove search consistency, and search
  consistency does not prove a zero-model warm replay actually matched selectors.

## 8. Prohibited in this runbook

- Re-running `add` or `flush` more than the single application-driven retry in
  §4c.
- Calling `client.delete(...)` against a user or agent memory scope. That is
  provider-wide deletion for that identity.
- Editing a skill revision in place. Repairs copy the revision, increment it, and
  preserve `source_case_id`.
- Loading a golden or fixture skill to make a demo proceed.
- Printing memory content, caregiver contact metadata, or the API key into a
  ticket. The check prints counts and IDs only, and its output is already
  redacted.
