# Runbook: Browserbase capacity exhaustion

Browserbase is the only production and demo browser path. There is no local or
fixture fallback. When capacity is gone, target browsing stops visibly and the
participant must be told the truth.

**Owner:** operator on duty. **Blast radius:** every new session, account-wide.

## 1. Trigger

Any of:

- `uv run ops/verify-browserbase-inventory.py` reports `degraded` with
  `concurrency_headroom` at or below zero, or names an orphaned session.
- The hosted `/ready` reports the `browserbase` capability as
  `capacity_exhausted`.
- The application surfaces `capacity_exhausted` or `session_limit` from
  `BrowserbaseErrorCode` on session create.
- A participant reports that the browser panel never appears.

## 2. Assess

```bash
uv run ops/verify-browserbase-inventory.py --include-recent-terminal
```

Read four fields:

| Field | Meaning |
|---|---|
| `total_concurrency_limit` | Slots the plan allows. |
| `active_sessions_total` | Slots consumed right now. |
| `active_sessions_webaccessible_owned` | Sessions carrying `webaccessibleSessionId`. Ours. |
| `active_sessions_other_owner` | Sessions in the same account that are not ours. |

Then classify:

| Observation | State | Meaning |
|---|---|---|
| `BROWSERBASE_API_KEY` absent | `unconfigured` | Nothing was checked. Install the secret first. |
| Key present, SDK unavailable | `configured` | No live call was made. Run under `uv run` from the repo root. |
| Headroom ≥ 1, no orphan, usage read | `verified` | Capacity is available. Exhaustion is not your fault path. |
| Headroom ≥ 1, usage unread | `healthy` | Capacity is available; the account is not fully inventoried. |
| Headroom ≤ 0, or an owned orphan is billing | `degraded` | This runbook applies. |

## 3. Contain

Tell the truth to the participant first. The application already blocks target
browsing when create fails; do not attempt to work around it.

- Do **not** start a demo or a teach run. Demo mode must refuse to start rather
  than claim a sponsor proof it cannot support.
- Do **not** point the app at a local browser, a fixture page, or another
  provider. Requirement: never substitute a local service for a cloud provider.
- Do **not** terminate sessions in bulk. Another operator or a live participant
  may hold one.

## 4. Recover

### 4a. Reclaim one identified orphaned session

An orphan is a WebAccessible-owned session older than
`BROWSERBASE_SESSION_TIMEOUT_SECONDS` (default 900) that is still `RUNNING`. The
inventory check names them individually.

Release exactly one session at a time, by ID, and only after confirming it is not
in use:

```bash
# 1. Re-read the inventory and copy one orphan ID.
uv run ops/verify-browserbase-inventory.py --json | python3 -m json.tool

# 2. Confirm nothing is attached: an in-use session appears in the app's own
#    session list. Check the hosted app before releasing anything.
curl -fsS https://webaccessible-care.fly.dev/ready | python3 -m json.tool \
  | python3 ops/lib/ops_redact.py

# 3. Release that one session. Substitute the ID; never loop over all sessions.
uv run python -c '
import os, sys
from browserbase import Browserbase

session_id = sys.argv[1]
client = Browserbase(api_key=os.environ["BROWSERBASE_API_KEY"])
current = client.sessions.retrieve(session_id)
print("status before:", current.status)
if current.status in {"ERROR", "TIMED_OUT", "COMPLETED"}:
    print("already terminal; nothing to release")
    raise SystemExit(0)
client.sessions.update(session_id, status="REQUEST_RELEASE")
print("release requested")
' "$ORPHAN_SESSION_ID"

# 4. Confirm the provider agrees it stopped. Never record "stopped" without this.
uv run python -c '
import os, sys
from browserbase import Browserbase
client = Browserbase(api_key=os.environ["BROWSERBASE_API_KEY"])
print("status after:", client.sessions.retrieve(sys.argv[1]).status)
' "$ORPHAN_SESSION_ID"
```

If step 4 does not report `COMPLETED`, `ERROR`, or `TIMED_OUT`, the session is
`termination_pending`. Record it as such, retry once after 60 seconds, and
escalate. Do not mark it stopped.

### 4b. Wait out a rate limit

`RATE_LIMITED` is not exhaustion. The application retries with bounded backoff.
Re-run the inventory after 60 seconds before taking any action:

```bash
uv run ops/verify-browserbase-inventory.py
```

### 4c. Foreign sessions are consuming the account

When `active_sessions_other_owner` is non-zero and headroom is gone, the account
is shared. Do not terminate sessions you do not own. Escalate to the account
owner and wait, or raise the plan's concurrency limit through the Browserbase
dashboard.

## 5. Rollback

There is nothing to roll back on the provider side: this runbook creates no
session and changes no configuration. If a change to
`BROWSERBASE_SESSION_TIMEOUT_SECONDS` or `BROWSERBASE_KEEP_ALIVE` was made to
address orphaning, revert it by re-setting the previous value:

```bash
# Restore the documented defaults. Values come from backend/app/config.py.
flyctl secrets set --app webaccessible-care \
  BROWSERBASE_SESSION_TIMEOUT_SECONDS=900 \
  BROWSERBASE_KEEP_ALIVE=false
flyctl status --app webaccessible-care
```

Setting a secret restarts the app. Follow
[runbook-fly-restart.md](runbook-fly-restart.md) to confirm it came back.

## 6. Verify

```bash
uv run ops/verify-browserbase-inventory.py
```

Recovery is complete when the check reports `verified`, or `healthy` with
headroom ≥ 1 if you deliberately skipped the usage read.

## 7. What this runbook does not prove

- Reclaimed headroom does not prove the WebAccessible session lifecycle works.
  Create, Live View, CDP attach, trusted participant input, and
  provider-confirmed termination remain unproven until a real run produces them.
- A session that appears `COMPLETED` in the inventory is not evidence of a
  WebAccessible teach run unless it carries `webaccessibleSessionId` metadata and
  the matching `BROWSER_SESSIONS` row exists in Snowflake.
- Headroom is a point-in-time reading. It does not reserve a slot.

## 8. Prohibited in this runbook

- Terminating more than one identified session per deliberate action, or looping
  over `client.sessions.list()` to release sessions in bulk.
- Terminating any session you did not confirm is WebAccessible-owned and idle.
- Requesting Live View or CDP URLs while diagnosing. They are capability URLs and
  are not needed to read capacity.
- Enabling any Browserbase Agent surface. `agentSurfaceUsed` must stay false;
  the inventory check fails the run if it is ever true.
- Rotating the API key as a first response. That breaks the hosted app and
  proves nothing about capacity.
