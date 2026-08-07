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
5. Store the Browserbase session ID, start/stop timestamps, and terminal state in Snowflake telemetry. Never store Browserbase keys in Snowflake.

## Evidence required before a cloud-execution claim

- A valid Browserbase API key is loaded from ignored local/secret management, never source control.
- A live Browserbase session is created and explicitly terminated through the documented API.
- The cold and warm demo runs show the same Browserbase path, embedded Live View, and a user-originated interaction trail.
- Dashboard/session evidence shows no autonomous Browserbase Agent capability was used for the product run.

## Provider limits and failure boundary

The verified Browserbase account is on the Free plan. Its provider-enforced session and browser-hour limits are a hard blocked state when reached; WebAccessible must surface that state and must not fall back to local browser automation. Existing dashboard sessions prove the account has reached the managed cloud path, but no WebAccessible Browserbase session has been claimed yet.

## Source traceability

- Browserbase dashboard setup instructions and authenticated project view, inspected 2026-08-07.
- [webaccessible-spec.md](../../webaccessible-spec.md), sections 2 and 5.
- [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md), toolchain and navigation authority.
