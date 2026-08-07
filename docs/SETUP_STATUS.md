# Live Integration Setup Status

Verified on 2026-08-07. This file records configuration and proof state without recording credentials.

## Local secret handling

- `.env` contains the locally provisioned Browserbase, EverOS, and Snowflake service credentials.
- `.env` and `.venv/` are ignored by Git; [.env.example](../.env.example) contains names/placeholders only.
- Do not copy local credentials into documentation, source code, Snowflake tables, screenshots, or submissions.

## Browserbase

| Item | Status |
|---|---|
| Account/project dashboard | Verified in Aside on the authenticated `Production project` (Free plan). |
| API key | Provisioned and stored only in ignored `.env`. |
| CLI | `browse 0.9.6` is installed globally from `browse@latest`; it uses `BROWSERBASE_API_KEY` only. |
| Execution contract | Browser Sessions through CDP and interactive Live View only; autonomous Browserbase Agent actions are prohibited. |
| Live account proof | Dashboard shows completed managed sessions; a WebAccessible-owned session is still pending implementation. |
| Provider boundary | Free-plan browser-hour and session limits must fail visibly. No local fallback is permitted. |

## EverMind / EverOS

| Item | Status |
|---|---|
| Account/memory space | Verified in Aside (`default_space`). |
| API key | Active dashboard key provisioned in ignored `.env`. |
| SDK | `everos-cloud 1.0.0` installed in `.venv`. |
| Live read proof | `get('agent_skill', agent_id='webaccessible')` succeeded. |
| Contract adjustment | `agent_skill` with `user_id` returns a live validation error; use the agent-scope adapter documented in [EVEROS.md](sponsors/EVEROS.md). |

## Snowflake

| Item | Status |
|---|---|
| CLI | Snowflake CLI `3.24.1` installed via Homebrew. |
| Warehouse | `WEBACCESSIBLE_WH`, X-Small, auto-suspend after 60 seconds. |
| Database/schema | `WEBACCESSIBLE.APP`. |
| Table | `SESSION_STEPS` created with the product-spec telemetry columns. |
| Service principal | `WEBACCESSIBLE_APP` with role `WEBACCESSIBLE_APP_ROLE`. |
| Credential | Role-restricted 90-day programmatic access token stored only in ignored `.env`. |
| CLI verification | `snow connection test --connection webaccessible` succeeded. |
| Query verification | The service user queried `SESSION_STEPS` successfully with the expected account, role, database, and schema. |

## Installed local dependencies

```text
Snowflake CLI 3.24.1
Browserbase `browse` CLI 0.9.6 (global)
everos-cloud 1.0.0
snowflake-connector-python 4.7.2
python-dotenv 1.2.2
```

## Remaining live gates

1. Create and explicitly terminate a disposable Browserbase session through the FastAPI CDP bridge, then capture Browserbase session and Live View evidence.
2. Implement the FastAPI Browserbase bridge, EverOS ownership adapter, and Snowflake writer.
3. Run one complete cold teach run and warm replay in Browserbase.
4. Persist the actual rows in `SESSION_STEPS`, render the cost curve, and obtain the first paid/prepaid Care Plan pilot evidence.
