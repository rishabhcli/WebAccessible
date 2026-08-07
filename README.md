# WebAccessible

**A web browser that does the errand for you.**

Most of the internet assumes you are quick with a mouse, comfortable with a form that
resets when you get one field wrong, and able to read grey text at eleven pixels. For a lot
of older adults, that means the DMV appointment does not get booked, the prescription does
not get refilled, and a daughter three time zones away gets another phone call that starts
"I'm sorry to bother you again."

WebAccessible is for that person. You tell it what you need — in your own words, the way
you would tell a person — and it goes and does it. You watch it happen in a real browser
window on the screen, and it tells you what it is doing in one plain sentence at a time.

## What it looks like to use

You open the page. There is no login, no password, no access code — it just opens.

Three common errands are offered as single buttons: get in line at the DMV, fill a grocery
cart, book a haircut. You can also just type what you want: *"renew my library book"*, or
*"order more cat food"*.

Then you watch. A browser window fills the left side of the screen, and beside it a running
list of what the agent is doing:

> Clicking on the driver license renewal option.
> Waiting for the page to load.
> Clicking Get in Line Now to join the queue at the nearest DMV office.

That list is written for you, not for a programmer. You will never see a CSS selector or an
element ID. When it finishes, it tells you plainly: your place in line is held, the
appointment is on the 14th at 10:40.

## It remembers what you did

This is the part that matters most, and it is the part a search engine cannot do for you.

Weeks later you can ask, out loud or by typing, *"did I already pay the electric bill?"* —
and get a real answer, because the run that paid it was stored as a memory:

> Yes. You paid the PG&E electric bill of $128.44 on the 27th from the checking account
> ending in 4412.

It answers from what actually happened. If there is no completed run, it says so rather
than guessing. That distinction is the whole point: a confident wrong answer about whether
a bill got paid is worse than no answer.

It also learns your routines. Once it has watched you do something a few times, it can
notice when one has lapsed — *"you last renewed your library books about a month ago"* —
and offer to do it again. Offers are dismissible and expire on their own; it does not nag.

## What it will not do

The agent drives the page itself: clicking, typing, choosing, navigating. Three things stop
it cold and hand the decision back to you:

- **Spending money.** It will fill a cart and walk right up to the checkout, then stop.
- **Deleting something.** Same.
- **Passwords.** It cannot read or type one, ever. It stops and asks you to sign in
  yourself, then carries on from there.

Everything short of that it just does, without interrupting you. Adding to a cart, joining
a queue, holding an appointment, filling in a form, following a link to another site — all
reversible, all uninterrupted. There is no list of approved websites; real errands wander
across hosts constantly (the DMV hands its queue to a company called Qmatic halfway
through), and stopping to ask at each handoff made the thing useless.

## Someone can help from a distance

There is a second door on the landing page, for the family member or caregiver. Behind it
is the history of what was done, what it cost, the readable version of each learned
routine, and a place to leave a short note that appears in the older adult's session.

It is deliberately a *view*, not a remote control. The person at the keyboard is still the
one whose errand it is.

## The demo tasks use a made-up person

The three offered errands run as a fictional woman — Margaret Whitfield, an invented
address, an `@example.com` mailbox that can never receive mail, and a phone number from the
block reserved for fiction. That way a demo can fill a real DMV form end to end without
putting a real person's details anywhere. Anything you type yourself is treated as yours
and filled from what you said, not from the persona.

## Honest status

The code is all here — the React interface, the FastAPI service, the browser bridge, the
memory adapter, the telemetry and cost tables, the reporting app.

What has *not* happened is a full frozen end-to-end qualification run. The DMV errand has
been driven end to end against the live site and completes. The haircut errand stalls,
because the booking site geolocates from the browser's IP address and serves the wrong
city. Grocery is unverified. See [`docs/SETUP_STATUS.md`](docs/SETUP_STATUS.md) for exactly
what has and has not been proven, and against which provider.

## How it is built

```text
React interface (landing, participant, caregiver)
                |
                v
FastAPI service, session state, live updates, local SQLite outbox
      |                    |                    |
      v                    v                    v
Browserbase          EverOS memory       Snowflake + Cortex
managed browser      what was done       planning, telemetry, cost
```

The browser the participant watches is a real managed Chrome session. The agent controls it
over CDP and only ever acts on an element from the same sanitized page snapshot the planner
reasoned about — it cannot be talked into clicking something that was not on the page.

Memories live in EverOS. Cost and telemetry live in Snowflake, priced from actual token
usage against dated rate cards; when a rate is missing it reports *unavailable* rather than
guessing. The local SQLite file is scratch space and an outbox, never the record.

```text
backend/app/
  api/            HTTP routes
  browser/        page observer, sanitizer, selector resolver, verifier
  domain/         safety rules, demo tasks, the fictional persona
  integrations/   Browserbase, EverOS, Snowflake/Cortex, local browser
  services/       autopilot, recall, replay, repair, telemetry, cost
web/src/          landing, participant dashboard, caregiver console
snowflake/        migrations, evidence queries, Streamlit app
scripts/          deployment, readiness, and memory seeding
docs/             decisions, provider contracts, evidence boundary
```

---

# Running it

Versions are pinned in [`.tool-versions`](.tool-versions): Node 26.5.1, Python 3.12.11,
pnpm 11.9.0. Snowflake deployment also needs the `snow` CLI; Fly needs `flyctl`.

### Setup

```bash
cp .env.example .env
make setup
```

### Run it as one app

This builds the interface and serves it and the API from a single origin — the simplest way
to actually use it:

```bash
pnpm build
PORT=3001 pnpm start
```

Open `http://localhost:3001`. API docs are at `/docs`.

### Run it for development

Two processes, with hot reload on both:

```bash
make backend                                        # API on :8000, --reload
VITE_API_BASE_URL=http://localhost:8000 pnpm dev    # interface on :5173
```

> If a change does not seem to take effect, check you are not talking to an older server
> process still running from a previous session — `ps aux | grep uvicorn`.

### Making the demos actually work

The offered errands need the Cortex planner. The deterministic local planner is a
development fallback that cannot navigate a real multi-step site, and `config.py` rejects
it outright for demo and production:

```bash
ACTION_PLANNER_PROVIDER="snowflake_cortex"     # in .env, needs Snowflake credentials
```

Leave `BROWSER_EXECUTION_PROVIDER=local` to drive a local Playwright Chromium with no cloud
browser account, or set it to `browserbase` for the managed session used in production.

### Giving it a history to remember

A fresh install has no memories, so there is nothing for recall to answer. To seed a
realistic one — errands with real dates, amounts, and confirmation numbers — written
through the live EverOS path:

```bash
uv run python scripts/seed-grandma-memory.py --verify
```

It prints one line to paste into the browser console so the page adopts that history.

### Checking it is alive

```bash
curl -fsS http://localhost:3001/health     # no providers called
curl -fsS http://localhost:3001/ready      # per-capability provider state
```

The stricter gate, which requires authorized providers and refuses fixture mode:

```bash
API_PUBLIC_URL=http://localhost:3001 ./scripts/live-readiness.sh
```

`/ready` reports each capability independently as `unconfigured`, `configured`,
`reachable`, `authorized`, `unavailable`, or `capacity_exhausted`. A green `/ready` is a
runtime preflight, not proof that an end-to-end run has been captured.

### The checks CI runs

```bash
uv run ruff check backend
uv run mypy backend
uv run pytest
pnpm typecheck
pnpm build
```

## Deploying

### Snowflake

The CLI connection defaults to `webaccessible` and must point at the scoped service role,
warehouse, `WEBACCESSIBLE` database, and `APP` schema.

```bash
snow connection test --connection webaccessible
SNOWFLAKE_CONNECTION=webaccessible ./scripts/apply-snowflake.sh
SNOWFLAKE_CONNECTION=webaccessible ./scripts/deploy-streamlit.sh
```

Migrations apply in order: `001_session_steps.sql`, `002_product_tables.sql`,
`003_evidence_views.sql`, `004_cortex_rate_cards.sql`. Rate-card rows must exist in
`COST_RATE_CARDS` before a real cost can be calculated.

### Fly

[`fly.toml`](fly.toml) defines the `webaccessible-care` app in `sjc` with a persistent
`/data` volume. First time only:

```bash
flyctl apps create webaccessible-care
flyctl volumes create webaccessible_data --app webaccessible-care --region sjc --size 1
```

Install secrets from your shell environment, then deploy:

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

flyctl deploy --app webaccessible-care
flyctl status --app webaccessible-care
curl -fsS https://webaccessible-care.fly.dev/health
```

## Further reading

- [`AGENTS.md`](AGENTS.md) — operating rules for working in this repository.
- [`webaccessible-spec.md`](webaccessible-spec.md) — original product spec. Predates the
  move to an autonomous agent; `AGENTS.md` supersedes it where they disagree.
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — work packages and evidence gates.
- [`SPONSORS.md`](SPONSORS.md), [`docs/sponsors/`](docs/sponsors/) — provider roles and
  what counts as proof for each.
- [`docs/SETUP_STATUS.md`](docs/SETUP_STATUS.md) — what is actually proven today.
- [`docs/demo-runbook.md`](docs/demo-runbook.md) — the qualification sequence.
