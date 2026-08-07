"""The curated demo tasks offered as one-tap starting points.

Three tasks are offered because they are the recurring errands this product exists for: a
government queue, a grocery order, and a standing appointment. Each one names a real site,
so the run shown on stage is the run a participant would get. Anything typed as a free
prompt is equally supported.

There is no origin allowlist. A run goes wherever the task leads it.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

from backend.app.contracts.models import DemoTask

DEMO_TASKS: Final[tuple[DemoTask, ...]] = (
    DemoTask(
        id="dmv-get-in-line",
        name="Get in line at the DMV",
        description=(
            "Joins the California DMV virtual queue for a field office so there is no "
            "waiting room."
        ),
        # DMV's own appointment shell loads an invisible reCAPTCHA on every page and can
        # divert managed browsers into its MyDMV login.  The site's reviewed "Get in Line"
        # path hands the task to this official Qmatic Mobile Ticket application.  Starting
        # at that legitimate destination avoids an inaccessible challenge rather than
        # attempting to defeat it.
        start_url="https://mt-cadmvoas.us.qmatic.cloud/branches",
        prompt=(
            "At the San Francisco DMV office, choose Office Visit and Driver Lic./ID Card, "
            "then get in line for a senior driver's license renewal."
        ),
        category="government",
    ),
    DemoTask(
        id="sprouts-groceries",
        name="Add groceries to the cart",
        description=(
            "Fills an Instacart cart from the Sprouts storefront with the usual weekly "
            "staples, stopping before checkout."
        ),
        start_url="https://www.instacart.com/store/sprouts/",
        prompt=(
            "Add milk, eggs, bananas, and bread to my Sprouts cart on Instacart. "
            "Stop before placing the order."
        ),
        category="shopping",
    ),
    DemoTask(
        id="haircut-appointment",
        name="Book a haircut",
        description=(
            "Opens the neighbourhood barbershop's booking page and holds the next open slot."
        ),
        # Booksy's own search resolves a location only through a Google-Places
        # autocomplete whose suggestions are drawn client-side; nothing in the URL sets
        # one, so a run that starts there types the city over and over and never gets a
        # result list.  Starting on the shop's public booking page -- the same page that
        # search would have led to -- puts the run straight onto services and times.
        start_url=(
            "https://booksy.com/en-us/162167_the-shop-barbershop_barber-shop_134715_san-francisco"
        ),
        prompt=(
            "Book a haircut at The Shop Barbershop in San Francisco at the earliest "
            "available time this week."
        ),
        category="appointment",
    ),
)

DEMO_TASKS_BY_ID: Final[dict[str, DemoTask]] = {task.id: task for task in DEMO_TASKS}


def origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _expand(origin: str) -> set[str]:
    """Allow the bare and www forms of an origin, which sites use interchangeably."""

    parsed = urlsplit(origin)
    host = parsed.netloc.lower()
    bare = host.removeprefix("www.")
    return {f"{parsed.scheme.lower()}://{bare}", f"{parsed.scheme.lower()}://www.{bare}"}


def demo_for_origin(url: str) -> DemoTask | None:
    origin = origin_of(url)
    for task in DEMO_TASKS:
        if origin in _expand(origin_of(task.start_url)):
            return task
    return None
