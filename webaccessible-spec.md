# WebAccessible — Build Spec
**Snowflake x Beta Fund x EverMind Hackathon · Aug 7 2026 · hard submit 4:00 PM · demo 3 min · audience vote 5 PM**

> A WebAccessible doesn't move you. It steadies you while you move yourself.

An assistant that lives in an older person's browser, notices when she's stuck, and walks her through the task one button at a time. She does the clicking. It remembers the route so the next time is instant and nearly free.

---

## 1. The people

| | |
|---|---|
| **Margaret, 78** | The user. Chrome on a laptop. Mild memory loss. Lives alone. Does 5-6 recurring things online: pays 3 bills, refills a prescription, joins a video call with the grandkids, checks her bank balance. |
| **Susan, 52** | The buyer. Margaret's daughter, 200 miles away. Currently gets 4-5 phone calls a week that all start "I can't find the thing." Pays $15/mo. |

The user and the customer are two different people. That shapes the whole product.

---

## 2. The exact flow

### Phase 0 — Open instantly

1. Margaret chooses **My tasks** and goes straight into the participant experience.
2. There is no participant sign-up, account, name, email, phone, or password form. The application creates a short-lived, scoped guest session for the browser with large text and voice guidance enabled.
3. Activity memory and proactive reminders default to off. They may only be enabled by a separate, explicit consent control; instant entry never opts the participant in.
4. **Optional but great:** Susan photographs a paper water bill from the caregiver console and uploads it. EverOS parses the PDF/image in one call and extracts the biller, account number, typical amount, due date. Those become facts before Margaret has done anything.

**Credentials: WebAccessible never stores or handles passwords.** It relies on Chrome's existing saved logins. At a login screen it says "click your email here, your password is saved" and Margaret clicks. WebAccessible navigates; it never authenticates. This removes the single scariest objection and cuts a day of work.

---

### Phase 1 — First run of a task (the teach run)

Two entry points.

**(a) Susan does it once.** She sits with Margaret or screen-shares, does the task normally. WebAccessible watches silently and records the route. This is the reliable path and the natural onboarding: *"do it with your mom once, it remembers forever."*

**(b) Margaret tries and gets stuck.** WebAccessible works the site out live. Slower, more expensive, still works.

**What "stuck" means, concretely.** WebAccessible is ambient, not summoned. It offers help when:

| Signal | Default threshold |
|---|---|
| No productive interaction on a page | 60s (45s inside a known task) |
| Same URL visited 3+ times | within 2 min |
| Fast scrolling, no clicks | 20s |
| Started a known skill's domain but left the remembered path | immediately |
| Form partly filled then idle | 40s |
| Page requests sensitive data and is not in her known sites | immediately |
| She clicks the WebAccessible button or says "help" | immediately |

**It offers once.** One calm line in the side panel, dismissible. If she dismisses, it backs off for 10 minutes on that page. Nagging is what makes this category hateful — get it right or the product is unusable.

---

### Phase 2 — The guidance loop

The repeating unit. One step at a time, never a list.

1. Side panel slides in. **Not** a popup over the content. Content stays where she left it.
2. One sentence, large type: *"Click the blue **Pay My Bill** button."*
3. The real button gets a soft halo and the page scrolls to it.
4. It reads the sentence aloud if voice is on.
5. **She clicks.** WebAccessible never clicks for her.
6. It verifies the page changed as expected, then gives the next step.

**If she clicks the wrong thing:** no correction, no scolding. *"That's alright — let's go back."* It re-routes from wherever she is.

**Before anything irreversible** — money moving, personal data submitted, anything deleted — it stops and states in plain words exactly what is about to happen and what the amount is. She presses the real button herself. WebAccessible never crosses that line, even in replay mode.

---

### Phase 3 — Done

Plain-language confirmation: *"The water bill is paid. $64.20. It'll show on your statement in a few days."*

Written to memory as a completed episode with date and amount. This powers the single most valuable thing the product says:

> Margaret, four days later: "Did I pay the water bill?"
> WebAccessible: "Yes — on the 6th, $64.20."

That answer is pure memory and it's worth the subscription on its own.

---

### Phase 4 — The route becomes a skill

The recorded trajectory becomes an EverOS **Case**. On success it distills into an **agent_skill** — a named, reusable route.

It's Markdown. Susan can read it, edit it, or delete it. That readability is the trust story for a product watching an elderly parent's browser.

---

### Phase 5 — Replay (next month) — *this is the demo*

Margaret says "pay the water bill" — or clicks it from a short list of her own routines.

WebAccessible loads the skill and replays: navigate → highlight → verify → next. **No reasoning about the website at all.** Same guidance experience for her, a fraction of the cost and time.

**When the site has changed:** a step's selector won't match. WebAccessible reasons about *that one step only*, gets past it, then repairs the skill. Cost bumps once, then returns to cheap. Sites get redesigned; the memory has to heal instead of shatter.

**Selector strategy for replay** — store three per step, try in order:
1. ARIA role + accessible name
2. Visible text content
3. CSS path

All three miss → fall back to reasoning → rewrite that step.

### Phase 5a — Remembered timing and proactive routine reminders

Activity memory and reminders are separate, explicit participant permissions. When activity memory
is enabled, every accepted event in the managed Browserbase session is retained as sanitized context:
task, origin (never path/query), event kind, outcome, and local time. Passwords, field values, raw DOM,
cookies, tokens, account numbers, and page content are never included.

After at least two starts of the same task, WebAccessible deterministically infers a daily, weekly, or
monthly timing pattern. If reminder permission is also enabled, the routine chooser may surface one
calm, dismissible suggestion near the learned time. It states why it appeared and how many observations
support it. This is an in-app routine suggestion, not a stuck/help prompt, and it respects snooze state.

Choosing **Start with guidance** is the permission boundary. It may create a task session, open the
confirmed skill's allowlisted start URL, and begin selector-first guidance. It may not click, type,
submit, accept a permission, or cross an irreversible boundary; Margaret still performs those actions.

---

### Phase 6 — Escalation to Susan

WebAccessible texts Susan when:
- Confidence is low or it's stuck after 2 attempts
- An unrecognized site is asking for money or identity details
- Margaret has abandoned the same task 3 times this week

Susan gets a link to a read-only view of the session. She can send a line that appears in the panel in her own name.

**It never guesses on money.** Stop and ask a human.

---

### Phase 7 — Scam shield (always on, not just during tasks)

Runs continuously against her memory of normal.

Fires on: a site she's never visited asking for SSN / bank / gift cards, fake "your computer is infected" overlays, spoofed brand pages, urgency language on a payment page.

Presentation is a **calm full-panel pause**, never a scary red alarm:

> *"Let's pause a moment. This page is asking for your Social Security number, and you've never used this site before. I've let Susan know."*

It does not close her tabs or take control. It interposes and notifies.

---

## 3. EverMind EverOS — exactly what it's doing

Every EverOS memory type earns a real job here. This is not memory bolted on; it's the reason the product works.

| EverOS type | What it holds for Margaret | Why it matters |
|---|---|---|
| `profile` (`user.md`) | Reading size, voice on, what she can do unaided, what she always forgets, tone that works | Loaded into every guidance prompt so instructions match her |
| `atomic_fact` | Water account 4471 · banks at Wells Fargo · **calls the electric bill "the light bill"** | The vocabulary facts are the unlock — her words map to real tasks |
| `agent_case` | One full recorded run of a task | Raw trajectory |
| `agent_skill` | The distilled route: "Pay Water Bill" | **The thing that makes replay cheap** |
| `episode` | "Aug 6: paid water bill $64.20, needed help at login" | Answers "did I already do that?" |
| `foresight` | "Water bill usually paid around the 6th; it's the 9th" | Proactive nudge, unprompted |

**Calls used**

```python
from everos_cloud import EverOS
client = EverOS(api_key=...)

# task start — find her routine + relevant facts, fuzzy phrasing OK
hit = client.search("the thing with the light bill", user_id="margaret",
                    top_k=5, include_profile=True)

# her routine list for the panel
skills = client.get("agent_skill", user_id="margaret")

# stream the run
client.add(session_id=sid, messages=[{...step...}])
client.flush(sid)            # force extraction at task end → Case → Skill

# Susan corrects something
client.edit("margaret", operations=[{"action":"add","type":"explicit_info",
    "data":{"category":"banking","description":"Switched to Chase in July"},
    "reason":"Susan updated"}])

# Susan's photo of the paper bill → parsed to facts in one call
client.upload("water-bill.jpg")
```

**Note:** EverOS reads are eventually consistent (index lags ~10-15s). Don't write-then-immediately-search in the demo path.

---

## 4. Snowflake — exactly what it's doing

Four real jobs. None of them is "and also a dashboard."

### 4.1 System of record

Every step of every session is a row.

```sql
CREATE TABLE SESSION_STEPS (
  session_id STRING, user_id STRING, step_no INT,
  task_name STRING, skill_id STRING,
  url_domain STRING, action STRING,
  model_used STRING, input_tokens INT, output_tokens INT, credits NUMBER(18,9),
  replayed_from_memory BOOLEAN,     -- the whole thesis lives in this column
  latency_ms INT, outcome STRING,   -- ok | wrong_click | stuck | escalated
  ts TIMESTAMP_NTZ
);
```

### 4.2 The cost proof — with an honest baseline

Cost per run of the same task, ordered by how many times she's done it. The baseline isn't simulated: **run #1 is a real cold run you actually paid for.** Every later run is measured against a number that genuinely happened.

```sql
SELECT task_name,
       ROW_NUMBER() OVER (PARTITION BY task_name ORDER BY MIN(ts)) AS run_no,
       SUM(input_tokens + output_tokens) AS tokens,
       SUM(credits) * 3.00 AS usd,
       BOOLOR_AGG(replayed_from_memory) AS used_memory
FROM SESSION_STEPS GROUP BY task_name, session_id ORDER BY task_name, run_no;
```

### 4.3 Cortex doing actual work

| Function | Job |
|---|---|
| `AI_EMBED` + similarity | Match her fuzzy phrasing ("the light bill thing") to the right stored skill |
| `AI_CLASSIFY` | Scam-shield page categories: `legitimate / phishing / fake_support / unknown_payment` |
| `AI_COUNT_TOKENS` | Price every step **before** spending it, so the family view shows real cost with no billing lag |
| `AI_COMPLETE` | Batch: turn a week of raw steps into Susan's plain-English weekly summary |
| **Cortex Analyst** | Susan asks "how did mom do this week?" in plain English over her real session data |

**Architecture honesty:** hot-path guidance runs on a fast API model, not in the warehouse — a round trip to Snowflake mid-click would feel slow. Snowflake owns the record, the money math, the skill matching, and everything analytical. Say this out loud if asked; it's a better answer than pretending it all runs in Cortex.

### 4.4 The dataset nobody else has

Across all users: which sites cause the most stuck events, escalations, and abandonment per visit.

```sql
SELECT url_domain,
       COUNT(*) FILTER (WHERE outcome IN ('stuck','escalated')) / COUNT(*) AS confusion_rate,
       COUNT(DISTINCT user_id) AS users
FROM SESSION_STEPS GROUP BY url_domain
HAVING users >= 5 ORDER BY confusion_rate DESC;
```

**"The websites hardest for people over 70, ranked."** Real, publishable, and a second business. Pharmacies, insurers and banks would pay for their own row.

### 4.5 ⚠️ Trap

`SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AISQL_USAGE_HISTORY` lags several hours and a fresh trial account will have **zero rows at 4 PM**. Do not build the live number on it. Compute cost with `AI_COUNT_TOKENS` + the published rate card and write it to your own table. Use ACCOUNT_USAGE only as a backup "Snowflake's own billing agrees" slide if rows have landed.

---

## 5. Architecture

```
Chrome extension (MV3)
├─ content script — halo overlay, click capture, DOM snapshot
└─ side panel — one instruction, large type, voice
        │  localhost:8000
        ▼
Python backend (FastAPI)
├─ stuck detector       (rules, no model — fast and cheap)
├─ guidance engine      (fast API model, cold runs only)
├─ replay engine        (no model — selector match + verify)
├─ EverOS client        (search / add / flush / get / upload)
└─ Snowflake writer     (every step → SESSION_STEPS)
        │
        ▼
Streamlit in Snowflake — Susan's weekly view + the cost curve
```

The replay engine calling **no model at all** is the point. That's where the cost collapse comes from and it's the sentence that explains the business.

---

## 6. Why memory is the business, not a feature

A browser agent that reasons out a website from scratch every time costs real money per task — vision calls, large DOM context, many steps. A few tasks a day and it costs more per month than a retiree's family will pay.

Replaying a remembered route costs almost nothing.

> **We can charge $15 a month because it remembers. Without memory this costs $60 a month to run and the product doesn't exist.**

---

## 7. Build order (11:00 → 4:00)

| Time | Item | Cut if late? |
|---|---|---|
| 11:00 | Snowflake trial + EverOS key + `SESSION_STEPS` table | no |
| 11:20 | Extension shell: side panel + halo overlay + click capture | no |
| 12:20 | Record a run → EverOS Case → Skill | no |
| 1:20 | Replay engine: selector match, verify, next | no |
| 2:00 | Step logging → Snowflake + cost-per-run query | no |
| 2:30 | Cost curve chart in Streamlit | no |
| 2:50 | Voice output | yes |
| 3:00 | Scam shield (`AI_CLASSIFY` on one real page) | yes |
| 3:10 | "Did I already pay it?" answer | keep — cheap and it lands |
| 3:20 | Susan SMS escalation | yes |
| **3:30** | **Stop building. Rehearse twice. Record backup video.** | **never** |

**Cut order if you're behind:** family dashboard → SMS → scam shield → voice → cross-user index. Never cut cold-run-vs-warm-run.

---

## 8. Demo script — 3 minutes, nothing staged

**0:00–0:25 — Who.** Margaret, 78, and her daughter Susan who gets five calls a week. No slide of statistics.

**0:25–1:20 — Cold run, live.** Real site, real task. It works out the page and walks her through it. She clicks. Meter on screen: ~40¢, 90 seconds, lots of thinking.

**1:20–1:40 — What it learned.** Open the skill file. Plain Markdown, readable by her daughter.

**1:40–2:20 — Warm run.** Same task again. Two cents, eight seconds, still her doing the clicking. One task, twice — nothing broken on purpose, nothing rigged.

**2:20–2:40 — The line.**
> "We can charge $15 a month because it remembers. Without memory this costs $60 to run and the product doesn't exist."

Cost curve on screen from real Snowflake rows.

**2:40–3:00 — The dataset.** "Every stuck moment across every user tells us which websites are hardest for people over 70. Nobody has that. We will."

### The thing that would actually win it
**Twenty seconds of a real older person finishing a real task on her own.** Phone video is fine. Record it before you write any code. It beats every chart in that room, and it's the one asset no other team can fake.

---

## 9. Risks

| Risk | Handling |
|---|---|
| Live browser automation dies on stage | Pick a task with **no login wall** for the live run. Record a backup video of the full real thing. |
| Real money on stage | Walk to the confirm screen and stop. That's what the product does anyway. |
| Venue wifi / site blocks automation | Test the exact target site before 1 PM. Have a second site ready. |
| Snowflake billing views empty at 4 PM | Own cost table via `AI_COUNT_TOKENS`. Never depend on ACCOUNT_USAGE. |
| EverOS index lag ~10-15s | Don't write-then-immediately-read in the demo path. Pre-warm the skill. |
| "How is this different from an AI browser?" | *"Every AI browser replaces the user. This one keeps her driving and just tells her where to turn."* Rehearse it out loud. |

---

## 10. Fast answers to the questions you'll get

**Why not just do it for her?** Because she loses the ability within a month. Susan isn't paying for the bill to get paid — she could do that herself in 30 seconds. She's paying so her mom can still do it.

**Isn't this just an agentic browser?** Those need you to say what you want. That's the whole interface. Someone with memory loss can't. The trigger here is her being stuck, not her issuing a command — and detecting stuck is the actual hard part.

**Privacy?** Memory is Markdown and Susan can read and delete any of it. WebAccessible never sees or stores a password; it uses Chrome's saved logins.

**Why does it need Snowflake?** It's the record of every step, the cost math that makes $15/mo possible, and the cross-user index of which websites fail older adults. That last one is a real dataset and a second business.
