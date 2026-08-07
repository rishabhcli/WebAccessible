#!/usr/bin/env python
"""Seed a grandmother's browsing history into EverOS so recall has something to answer.

Everything written here goes through the live EverOS provider -- the same `add`/`flush`
extraction path a real task run uses. Nothing is written to a local file, and nothing is
faked in the app: `RecallService` reads these back out of EverOS through
`recall_context`, so "Did I already pay the electric bill?" is answered from the sponsor's
memory or not at all.

Each errand below becomes one extraction session. The messages are written the way a real
run reports itself: what she asked for, then what the agent actually did, with the
concrete outcome the answer will need (a date, an amount, a confirmation number).

    uv run python scripts/seed-grandma-memory.py
    uv run python scripts/seed-grandma-memory.py --user-id wa-<uuid> --verify

The default user id is a fixed UUID so the browser can adopt it in one line; the script
prints that line when it finishes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings  # noqa: E402
from backend.app.integrations.everos.client import (  # noqa: E402
    EverOSAdapter,
    EverOSProvider,
)

# Shaped to satisfy the participant-id pattern the web app enforces, so a browser can be
# pointed at this history without editing any code.
DEFAULT_USER_ID = "wa-11111111-1111-4111-8111-111111111111"

# Days ago -> one completed errand. Ordered oldest first so the recency of the most
# recent answer is unambiguous.
ERRANDS: tuple[tuple[int, str, str], ...] = (
    (
        34,
        "I need to renew my library books before they're overdue.",
        "I renewed all 3 library books on the San Francisco Public Library site. They are "
        "now due on the 18th. No fines were owed.",
    ),
    (
        28,
        "Can you check whether my Social Security deposit came through?",
        "I checked the Social Security account. The monthly deposit of $1,847.00 landed on "
        "the 3rd into the checking account ending in 4412.",
    ),
    (
        21,
        "I want to refill my blood pressure prescription.",
        "I refilled the lisinopril prescription at the CVS on Geary Boulevard. It is ready "
        "for pickup and the confirmation number is RX-40192. The copay is $12.00.",
    ),
    (
        16,
        "Order my usual groceries from Sprouts.",
        "I filled the Sprouts cart on Instacart with the usual weekly staples: milk, eggs, "
        "bananas, and bread. The cart totalled $43.18 and I stopped before placing the "
        "order.",
    ),
    (
        11,
        "Pay the electric bill please.",
        "I paid the PG&E electric bill of $128.44 on the 27th from the checking account "
        "ending in 4412. The confirmation number is PGE-88213421.",
    ),
    (
        7,
        "I need an appointment at the DMV to renew my license.",
        "I joined the California DMV virtual queue for the Fell Street field office for a "
        "driver license renewal. The appointment is on the 14th at 10:40 AM.",
    ),
    (
        4,
        "Book me a haircut sometime this week.",
        "I booked a haircut at Serena's Salon on Clement Street for Thursday at 11:00 AM. "
        "The booking reference is BK-77310.",
    ),
    (
        2,
        "Can you find that recipe for lemon bars I looked at?",
        "I found the lemon bar recipe on Sally's Baking Addiction that you read last "
        "month, and left it open. It needs 4 lemons and takes about an hour.",
    ),
)

# Stable preferences a grandmother's history implies. Recall grounds answers in these
# alongside the episodes.
FACTS: tuple[str, ...] = (
    "I live in the Richmond district of San Francisco.",
    "I use the checking account ending in 4412 for household bills.",
    "My pharmacy is the CVS on Geary Boulevard.",
    "I like appointments in the late morning, never before ten.",
    "I read the news on SFGate most mornings.",
    "My daughter Susan helps me when something goes wrong.",
)


async def seed(user_id: str, verify: bool) -> int:
    settings = Settings()
    if not settings.everos_configured:
        print("EverOS is not configured; set EVEROS_API_KEY. Nothing was written.")
        return 1

    provider = EverOSProvider(settings)
    now = datetime.now(UTC)
    written = 0

    for days_ago, asked, done in ERRANDS:
        when = now - timedelta(days=days_ago)
        session_id = f"seed-{uuid.uuid4()}"
        # The provider rejects an explicit `timestamp` on a message, so the date is
        # carried in the text where a recall answer can quote it anyway.
        dated = f"{done} This was completed on {when:%B %d, %Y}."
        try:
            await provider.add(
                session_id,
                user_id,
                [
                    {"role": "user", "content": asked},
                    {"role": "assistant", "content": dated},
                ],
            )
            await provider.flush(session_id)
        except Exception as error:  # noqa: BLE001 - report the provider's own words
            print(f"  FAILED  {asked[:48]!r}: {error}")
            continue
        written += 1
        print(f"  wrote   {when:%Y-%m-%d}  {done[:64]}...")

    facts_session = f"seed-{uuid.uuid4()}"
    try:
        await provider.add(
            facts_session,
            user_id,
            [{"role": "user", "content": fact} for fact in FACTS],
        )
        await provider.flush(facts_session)
        print(f"  wrote   {len(FACTS)} standing facts")
    except Exception as error:  # noqa: BLE001
        print(f"  FAILED  standing facts: {error}")

    print(f"\n{written}/{len(ERRANDS)} errands written to EverOS for {user_id}.")

    if verify:
        print("\nReading it back through the same path the app uses:")
        adapter = EverOSAdapter(settings)
        for question in (
            "Did I already pay the electric bill?",
            "When is my DMV appointment?",
            "Where do I pick up my prescription?",
        ):
            try:
                answer = await adapter.answer_episode(user_id, question)
            except Exception as error:  # noqa: BLE001
                print(f"  {question}\n    provider error: {error}")
                continue
            print(f"  {question}\n    found={answer.found}  {answer.answer[:120]}")

    print("\nPoint a browser at this history by running one line in its console:")
    print(f'  localStorage.setItem("webaccessible.participantUserId", "{user_id}")')
    return 0 if written else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="read the seeded episodes back out of EverOS after writing",
    )
    args = parser.parse_args()
    return asyncio.run(seed(args.user_id, args.verify))


if __name__ == "__main__":
    raise SystemExit(main())
