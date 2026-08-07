"""The curated demo tasks and the origin allowlist that bounds every autonomous run.

Three tasks are offered as one-tap demos because they are the recurring errands this
product exists for: a government queue, a grocery order, and a standing appointment. Each
one names a real site, so the run shown on stage is the run a participant would get.

Anything typed as a free prompt is also allowed. The allowlist below is not a restriction
on what may be asked; it is the set of origins an autonomous run may *start* on and stay
within without a fresh confirmation, which is what keeps a mistyped prompt from wandering
onto a checkout page nobody reviewed.
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
        start_url="https://www.dmv.ca.gov/portal/appointments/",
        prompt="Get in line at the nearest DMV office for a driver license renewal.",
        category="government",
    ),
    DemoTask(
        id="whole-foods-groceries",
        name="Add groceries to the cart",
        description=(
            "Fills an Amazon Whole Foods cart with the usual weekly staples, stopping "
            "before checkout."
        ),
        start_url="https://www.amazon.com/alm/storefront",
        prompt=(
            "Add milk, eggs, bananas, and bread to my Whole Foods cart. "
            "Stop before placing the order."
        ),
        category="shopping",
    ),
    DemoTask(
        id="haircut-appointment",
        name="Book a haircut",
        description=(
            "Finds the next open slot at a salon that takes online appointments and holds it."
        ),
        start_url="https://www.greatclips.com/salons/online-check-in",
        prompt="Book a haircut at the closest salon at the earliest time this week.",
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


# Origins reached in the normal course of the curated tasks: identity providers, store
# subdomains, and booking hosts. A run that leaves this set pauses for confirmation.
_ADDITIONAL_ORIGINS: Final = frozenset(
    {
        "https://www.dmv.ca.gov",
        "https://qless.com",
        "https://www.amazon.com",
        "https://smile.amazon.com",
        "https://www.greatclips.com",
        "https://online-booking.greatclips.com",
    }
)

DEMO_ORIGINS: Final[frozenset[str]] = frozenset(
    origin
    for task in DEMO_TASKS
    for origin in _expand(origin_of(task.start_url))
) | frozenset(
    expanded for origin in _ADDITIONAL_ORIGINS for expanded in _expand(origin)
)


def demo_for_origin(url: str) -> DemoTask | None:
    origin = origin_of(url)
    for task in DEMO_TASKS:
        if origin in _expand(origin_of(task.start_url)):
            return task
    return None


def is_allowlisted(url: str) -> bool:
    """Return whether an autonomous run may continue on this origin unprompted."""

    return origin_of(url) in DEMO_ORIGINS
