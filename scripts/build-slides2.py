#!/usr/bin/env python3
"""Render the WebAccessible deck to PNGs under `web/public/slides2/deck`.

The deck is written as HTML and photographed at 1920x1080 rather than authored in a
slide tool, so it is reviewable in a diff, regenerates in one command, and can embed a
real screenshot of a real run instead of a mock-up.

    uv run python scripts/build-slides2.py

The screenshot on the "watch it work" slide comes from `web/public/slides2/live-run.png`.
Recapture it with `scripts/capture-slide-screenshot.py` while the app is running.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "slides2" / "deck"
WIDTH, HEIGHT = 1920, 1080

# Ink, moss, and a warm signal amber. Dark by choice: a projected deck reads better dark,
# and every slide keeps text well above the 7:1 contrast this product is built around.
THEME = """
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap');

:root {
  --ink: #071410;
  --ink-2: #0d2a1f;
  --paper: #f3f7f3;
  --moss: #7fd3a6;
  --moss-deep: #1f7a54;
  --amber: #f5b64c;
  --muted: #a8c2b4;
  --line: rgba(127, 211, 166, 0.22);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  width: 1920px;
  height: 1080px;
  overflow: hidden;
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif;
  color: var(--paper);
  background: var(--ink);
}

.slide {
  position: relative;
  width: 1920px;
  height: 1080px;
  padding: 96px 120px;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(1200px 760px at 82% -12%, rgba(31, 122, 84, 0.55), transparent 62%),
    radial-gradient(900px 620px at -8% 108%, rgba(245, 182, 76, 0.16), transparent 60%),
    var(--ink);
}

/* A faint horizon rule under every slide: the deck's one repeating mark. */
.slide::after {
  content: '';
  position: absolute;
  left: 120px;
  right: 120px;
  bottom: 72px;
  height: 1px;
  background: linear-gradient(90deg, var(--moss), transparent 70%);
  opacity: 0.5;
}

.eyebrow {
  font-size: 25px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--moss);
  font-weight: 700;
}

h1 { font-size: 92px; line-height: 1.04; letter-spacing: -0.02em; }
h2 { font-size: 74px; line-height: 1.06; letter-spacing: -0.02em; margin-top: 20px; }
p  { font-size: 34px; line-height: 1.5; color: var(--muted); }

.lead { font-size: 40px; line-height: 1.45; color: var(--paper); max-width: 1380px; }

.foot {
  position: absolute;
  left: 120px;
  bottom: 34px;
  font-size: 22px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(168, 194, 180, 0.75);
}
.page {
  position: absolute;
  right: 120px;
  bottom: 34px;
  font-size: 22px;
  color: rgba(168, 194, 180, 0.75);
}

.cards { display: grid; gap: 34px; margin-top: 56px; }
.cards--3 { grid-template-columns: repeat(3, 1fr); }
.cards--2 { grid-template-columns: repeat(2, 1fr); }

.card {
  background: linear-gradient(180deg, rgba(31, 122, 84, 0.22), rgba(13, 42, 31, 0.5));
  border: 1px solid var(--line);
  border-radius: 26px;
  padding: 42px 40px;
}
.card h3 { font-size: 38px; line-height: 1.2; margin-bottom: 16px; }
.card p { font-size: 27px; line-height: 1.45; }
.card .num {
  display: inline-block;
  font-size: 24px;
  font-weight: 700;
  color: var(--ink);
  background: var(--amber);
  border-radius: 999px;
  padding: 6px 18px;
  margin-bottom: 22px;
}

.rule { width: 132px; height: 8px; border-radius: 999px; background: var(--amber); }

.mark {
  display: inline-flex;
  align-items: center;
  gap: 20px;
  font-size: 26px;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: var(--moss);
  font-weight: 700;
}
.mark span.dot {
  width: 20px; height: 20px; border-radius: 6px; background: var(--amber);
}

.stat { font-size: 128px; line-height: 1; color: var(--amber); font-weight: 700; }
.stat-note { font-size: 28px; color: var(--muted); margin-top: 14px; }

.shot {
  margin-top: 44px;
  border-radius: 24px;
  border: 1px solid var(--line);
  overflow: hidden;
  box-shadow: 0 60px 120px -60px rgba(0, 0, 0, 0.9);
  background: #fff;
}
.shot img { display: block; width: 100%; max-height: 690px; object-fit: cover; object-position: top; }

.flow { display: flex; align-items: stretch; gap: 26px; margin-top: 60px; }
.flow .step {
  flex: 1;
  border: 1px solid var(--line);
  border-radius: 22px;
  padding: 36px 32px;
  background: rgba(13, 42, 31, 0.55);
}
.flow .step b { display: block; font-size: 34px; margin-bottom: 12px; }
.flow .step p { font-size: 25px; }
.flow .arrow { align-self: center; color: var(--amber); font-size: 46px; }

.stops { display: grid; grid-template-columns: repeat(3, 1fr); gap: 30px; margin-top: 56px; }
.stop {
  border-radius: 24px;
  padding: 40px 36px;
  border: 1px solid rgba(245, 182, 76, 0.45);
  background: linear-gradient(180deg, rgba(245, 182, 76, 0.16), rgba(13, 42, 31, 0.5));
}
.stop b { font-size: 36px; display: block; margin-bottom: 14px; color: var(--amber); }
.stop p { font-size: 26px; }

.list { margin-top: 46px; display: grid; gap: 26px; }
.list li { list-style: none; display: flex; gap: 24px; align-items: flex-start; }
.list li b { color: var(--moss); font-size: 32px; min-width: 44px; }
.list li p { font-size: 31px; color: var(--paper); }
.list li p em { color: var(--muted); font-style: normal; }

.stack { display: grid; grid-template-columns: repeat(2, 1fr); gap: 28px; margin-top: 50px; }
.stack div {
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 32px 34px;
  background: rgba(13, 42, 31, 0.5);
}
.stack b { font-size: 31px; color: var(--moss); display: block; margin-bottom: 10px; }
.stack p { font-size: 25px; }
"""


def frame(number: int, body: str, foot: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>{THEME}</style></head>
<body><section class="slide">{body}
<div class="foot">{foot}</div><div class="page">{number:02d}</div>
</section></body></html>"""


TITLE = """
<div style="margin-top:70px">
  <div class="mark"><span class="dot"></span> For older adults on the modern web</div>
  <h1 style="font-size:184px;margin-top:44px;letter-spacing:-0.035em">WebAccessible</h1>
  <div class="rule" style="margin:44px 0 40px"></div>
  <p class="lead" style="font-size:48px;max-width:1500px">
    An agent that <strong>does the errand for you</strong> — it opens a real browser,
    joins the DMV queue, fills the grocery cart, books the appointment, and says out loud
    what it is doing at every step.
  </p>
  <p style="margin-top:38px;font-size:33px;max-width:1420px">
    Built for people who are perfectly capable of deciding what they want, and are being
    shut out by cookie walls, tiny text, five-step checkouts, and forms that time out.
  </p>
</div>
"""

PROBLEM = """
<div class="eyebrow">The problem</div>
<h2>The web got harder exactly as it became mandatory.</h2>
<div class="cards cards--3">
  <div class="card">
    <span class="num">01</span>
    <h3>Errands moved online</h3>
    <p>Renewing a licence, refilling a prescription, ordering groceries. The counter and
    the phone line closed; the website is now the only door.</p>
  </div>
  <div class="card">
    <span class="num">02</span>
    <h3>The door keeps changing</h3>
    <p>Consent banners, sign-in nags, dropdowns that vanish, sessions that expire
    mid-form. Every site is a new set of rules learned under time pressure.</p>
  </div>
  <div class="card">
    <span class="num">03</span>
    <h3>So the errand gets skipped</h3>
    <p>Or it becomes a phone call to an adult child. Independence quietly turns into
    dependence, one abandoned form at a time.</p>
  </div>
</div>
<p style="margin-top:56px;font-size:33px;max-width:1500px">
  Screen readers and zoom make a page <em style="color:var(--paper);font-style:normal">
  perceivable</em>. They do not make a fourteen-step checkout
  <em style="color:var(--paper);font-style:normal">completable</em>. That gap is the
  product.
</p>
"""

SOLUTION = """
<div class="eyebrow">What it does</div>
<h2>Say the errand. Watch it happen.</h2>
<p class="lead" style="margin-top:30px">
  One tap, or one plain sentence. No URL, no account, no password — entry is
  passwordless and the agent never types a password on anyone's behalf.
</p>
<div class="cards cards--3">
  <div class="card">
    <h3>Get in line at the DMV</h3>
    <p>Joins the California DMV's virtual queue for a field office, so there is no
    waiting room and no morning lost.</p>
  </div>
  <div class="card">
    <h3>Add groceries to the cart</h3>
    <p>Searches the store, adds each item, answers the pickup-or-delivery dialog, and
    stops before placing the order.</p>
  </div>
  <div class="card">
    <h3>Book a haircut</h3>
    <p>Opens the barbershop's booking page, picks the haircut, and holds the next open
    slot for review.</p>
  </div>
</div>
<p style="margin-top:52px;font-size:31px">
  Anything else typed as a sentence works the same way — with no address given, the run
  starts from a search and finds the site itself.
</p>
"""

SCREENSHOT = """
<div style="display:flex;align-items:flex-end;justify-content:space-between">
  <div>
    <div class="eyebrow">Live run · not a mock-up</div>
    <h2 style="font-size:64px">Mid-errand: filling a grocery cart at Target.</h2>
  </div>
  <p style="max-width:520px;font-size:26px;text-align:right">
    The managed browser on the left. On the right, a plain-language account of every step
    as it happens — and a Stop button that is always one tap away.
  </p>
</div>
<div class="shot"><img src="../live-run.png" alt="The agent partway through the grocery task"></div>
"""

HOW = """
<div class="eyebrow">How it works</div>
<h2>Read the page. Plan one step. Say it. Do it.</h2>
<div class="flow">
  <div class="step"><b>Read</b><p>The live page is reduced to the controls a person could
  actually use — labels, roles, and what each one belongs to.</p></div>
  <div class="arrow">→</div>
  <div class="step"><b>Plan</b><p>Claude, on Snowflake Cortex, chooses exactly one next
  action from that list. It cannot invent a target it was never shown.</p></div>
  <div class="arrow">→</div>
  <div class="step"><b>Check</b><p>Money, deletion, and password fields stop the run
  before the click, not after.</p></div>
  <div class="arrow">→</div>
  <div class="step"><b>Narrate</b><p>One short sentence in plain words, streamed to the
  screen as the step happens.</p></div>
</div>
<p style="margin-top:60px;font-size:31px;max-width:1560px">
  Overlays get dismissed, autocompletes get real keystrokes, new tabs get followed, and
  while a dialog is open nothing behind it can be clicked. Real sites are the
  specification.
</p>
"""

BOUNDARIES = """
<div class="eyebrow">Where autonomy stops</div>
<h2>Reversible things proceed. Irreversible things ask.</h2>
<div class="stops">
  <div class="stop"><b>Money</b><p>Filling a cart is reversible, so it proceeds. Paying is
  not, so the run pauses and hands the decision back.</p></div>
  <div class="stop"><b>Deletion</b><p>Nothing is removed or cancelled without a person
  saying so first.</p></div>
  <div class="stop"><b>Passwords</b><p>The agent cannot read or type one. It stops, says
  so, and waits while the person signs in themselves.</p></div>
</div>
<p style="margin-top:56px;font-size:32px;max-width:1560px">
  Everything else — clicking, typing an address, choosing a time, following a link to any
  host — the agent does itself. There is no origin allowlist; a run goes wherever the
  errand leads.
</p>
"""

CAREGIVER = """
<div class="eyebrow">The caregiver console</div>
<h2>Family can see what happened without doing it for them.</h2>
<ul class="list">
  <li><b>01</b><p>Every run, every step, and every pause — visible after the fact.
  <em>No screen sharing, no phone call.</em></p></li>
  <li><b>02</b><p>Escalations arrive where the caregiver already is, with the exact step
  that needs a human.</p></li>
  <li><b>03</b><p>What the agent remembers is the participant's to see and switch off.
  <em>Memory is opt-in, and reminders require it.</em></p></li>
</ul>
<p style="margin-top:64px;font-size:32px;max-width:1520px">
  The point is not surveillance. It is that an adult child can stop being the help desk
  while still knowing the prescription got ordered.
</p>
"""

MEMORY = """
<div class="eyebrow">Memory and reminders</div>
<h2>It remembers the errand so nobody has to re-explain it.</h2>
<div class="cards cards--2">
  <div class="card">
    <h3>Ask about what already happened</h3>
    <p>“When is the DMV appointment you booked?” is answered from the run itself —
    grounded in the steps that actually took place, not guessed.</p>
  </div>
  <div class="card">
    <h3>Reminders that arrive first</h3>
    <p>A standing errand comes back on its own schedule and is offered before it is
    overdue, rather than after.</p>
  </div>
</div>
<div style="margin-top:70px;display:flex;gap:110px;align-items:flex-end">
  <div><div class="stat">0</div><div class="stat-note">passwords typed by the agent</div></div>
  <div><div class="stat">1</div><div class="stat-note">tap to start an errand</div></div>
  <div><div class="stat">Any</div><div class="stat-note">site — no allowlist</div></div>
</div>
"""

STACK = """
<div class="eyebrow">The stack</div>
<h2>Cloud-run, and boring on purpose.</h2>
<div class="stack">
  <div><b>Claude on Snowflake Cortex</b><p>Chooses each next action and writes the
  narration. Structured output, one action per step.</p></div>
  <div><b>Browserbase + Playwright</b><p>A managed Chromium the participant can watch
  live, with local Chromium for development.</p></div>
  <div><b>Snowflake</b><p>Runs, steps, escalations, and grounded recall over what
  actually happened.</p></div>
  <div><b>FastAPI + React on Fly.io</b><p>Streamed updates over SSE, large type, and
  passwordless entry.</p></div>
</div>
"""

CLOSE = """
<div style="margin-top:120px">
  <div class="mark"><span class="dot"></span> WebAccessible</div>
  <h1 style="font-size:124px;margin-top:40px;max-width:1560px">
    One sentence. A visible run. A person still in charge.
  </h1>
  <div class="rule" style="margin:52px 0 42px"></div>
  <p class="lead" style="font-size:42px;max-width:1500px">
    The web will not get simpler. Somebody should be able to use it on your grandmother's
    behalf, in the open, where she can watch and stop it.
  </p>
</div>
"""

SLIDES: tuple[tuple[str, str], ...] = (
    (TITLE, "WebAccessible"),
    (PROBLEM, "The problem"),
    (SOLUTION, "What it does"),
    (SCREENSHOT, "Live run"),
    (HOW, "How it works"),
    (BOUNDARIES, "Where autonomy stops"),
    (CAREGIVER, "Caregiver console"),
    (MEMORY, "Memory and reminders"),
    (STACK, "The stack"),
    (CLOSE, "WebAccessible"),
)


async def main() -> None:
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2
        )
        for number, (body, foot) in enumerate(SLIDES, start=1):
            path = OUT / f"slide-{number:02d}.html"
            path.write_text(frame(number, body, foot), encoding="utf-8")
            await page.goto(path.as_uri(), wait_until="networkidle")
            # Give the webfont a beat so the type is not photographed mid-swap.
            await page.wait_for_timeout(900)
            await page.screenshot(path=str(OUT / f"slide-{number:02d}.png"))
            path.unlink()
            print(f"slide-{number:02d}.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
