# Browserbase Execution Contract

## Role

Browserbase is the sole browser-execution environment for WebAccessible. Every target-site navigation, observation, highlight, verification, and user action occurs inside a managed Browserbase Browser Session. It is an execution provider, not a sponsor, but its real cloud path is non-negotiable for the product.

## Allowed API surface

FastAPI creates and controls Browserbase Browser Sessions through CDP. Browserbase Live View is the embedded remote browser surface used by Margaret.

Browserbase autonomous Agent capabilities are prohibited. A goal-based agent could independently act on a page, which violates the promise that Margaret performs every click and submit.

## User-control contract

- Margaret uses interactive Browserbase Live View and performs the actual pointer/keyboard action.
- FastAPI may navigate only under the active guidance state, inspect sanitized accessibility/DOM data, scroll or highlight a verified target, and verify a user-originated result.
- FastAPI must not issue a page click, populate credentials, enter payment/identity data, submit a form, close a tab, or advance an irreversible action.
- Before money movement, sensitive-data submission, or deletion, guidance pauses and names the action/amount. The remote session waits for Margaret's actual action or Susan's escalation path.

## Lifecycle

1. FastAPI validates `BROWSERBASE_API_KEY`; the API key resolves the Browserbase project, so no project ID is configured.
2. Create one Browserbase session per active task and persist its Browserbase session ID with the WebAccessible session.
3. Attach through CDP and expose Live View while streaming only the minimal sanitized page/interaction signals needed by the stuck detector and replay engine.
4. Explicitly terminate the Browserbase session on completion, escalation, abandonment, or backend failure.
5. On backend startup, list only `PENDING` and `RUNNING` sessions, require the exact WebAccessible metadata marker for the current environment, and terminate those orphaned sessions before telemetry starts. Unmarked sessions and sessions from another environment are never touched.
6. Store the Browserbase session ID, start/stop timestamps, and terminal state in Snowflake telemetry. Never store Browserbase keys in Snowflake.

## Sanitized live provider qualification

On 2026-08-07, the implemented adapter and controller completed one live provider-only qualification against the exact W3C sandwich checkbox target. The retained session reference is the first 12 characters of its SHA-256 digest, `e05ede2a19f4`; the raw session ID and Live View URL are intentionally omitted.

- Managed-session create plus CDP attachment completed in 4.49 seconds.
- Browserbase returned an HTTPS Live View, and the controller observed the configured W3C origin and normalized target path.
- The observation-only snapshot completed in 70 ms and returned 49 visible candidates: 44 links, 4 checkboxes, and 1 candidate without an explicit role. No sensitive candidates were reported.
- Explicit controller termination completed in 153 ms. Browserbase returned `COMPLETED` with an end timestamp, and a separate provider list readback confirmed the terminal session.
- Session metadata recorded `agentSurfaceUsed=false`. No Browserbase Agent operation, click, typing, form fill, submit, or other target-page action was performed.

This proves the isolated create -> CDP -> Live View -> observe -> terminate provider lifecycle. It does not replace the required cold and warm demo runs or prove a trusted participant-input trail.

## Evidence required before a cloud-execution claim

- A valid Browserbase API key is loaded from ignored local/secret management, never source control.
- A live Browserbase session is created and explicitly terminated through the documented API.
- The cold and warm demo runs show the same Browserbase path, embedded Live View, and a user-originated interaction trail.
- Dashboard/session evidence shows no autonomous Browserbase Agent capability was used for the product run.

## Provider limits and failure boundary

The verified Browserbase account is on the Free plan. Its provider-enforced session and browser-hour limits are a hard blocked state when reached; WebAccessible must surface that state and must not fall back to local browser automation. The sanitized provider qualification above proves the WebAccessible managed-session lifecycle, while the full cold/warm participant demo path remains a separate evidence gate.

## Source traceability

- Browserbase dashboard setup instructions and authenticated project view, inspected 2026-08-07.
- [webaccessible-spec.md](../../webaccessible-spec.md), sections 2 and 5.
- [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md), toolchain and navigation authority.
