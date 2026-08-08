"""The curated demo tasks offered as one-tap starting points.

Three tasks are offered because they are the recurring errands this product exists for: a
government queue, a grocery order, and a standing appointment. Each one names a real site,
so the run shown on stage is the run a participant would get. Anything typed as a free
prompt is equally supported.

There is no origin allowlist. A run goes wherever the task leads it.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import quote_plus, urlsplit

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
        # The office has to be one this Qmatic list actually offers. It named San
        # Francisco before, which is not on it, so the run scrolled the branch list
        # looking for a branch that was never there and then asked for help.
        prompt=(
            "At the Chico DMV office, choose Office Visit and Driver Lic./ID Card, "
            "then get in line for a senior driver's license renewal."
        ),
        category="government",
    ),
    DemoTask(
        id="target-groceries",
        name="Add groceries to the cart",
        description=(
            "Fills a Target cart with the usual weekly grocery staples, stopping before "
            "checkout."
        ),
        start_url="https://www.target.com/c/grocery/-/N-5xt1a",
        prompt=(
            "Add milk, eggs, bananas, and bread to my Target cart. "
            "Stop before placing the order."
        ),
        category="shopping",
    ),
    DemoTask(
        id="haircut-appointment",
        name="Book a haircut",
        description=(
            "Opens the barbershop's booking page, picks the haircut, and holds the next "
            "open slot."
        ),
        # This used to start at Booksy's search page, where the run stalled: Booksy
        # resolves a location only through an autocomplete drawn client-side -- no URL
        # sets one -- so the run typed "San Francisco, CA" on every remaining step and
        # never got a result list.  Booksy's own shop pages are no better: their Book
        # buttons do nothing under an automated browser.  Square Appointments hosts the
        # whole errand -- services, times, and the hold -- as ordinary page controls, so
        # the run can actually finish it.
        start_url=(
            "https://squareup.com/appointments/book/2R6BZ1QJ91ECW/society-barbershop-san-jose-ca"
        ),
        prompt=(
            "Book a haircut at Society Barbershop at the earliest available time this "
            "week. Stop before paying."
        ),
        category="appointment",
    ),
)

DEMO_TASKS_BY_ID: Final[dict[str, DemoTask]] = {task.id: task for task in DEMO_TASKS}


def search_url_for(prompt: str) -> str:
    """Where a run starts when nobody supplied an address: a search for the errand.

    DuckDuckGo's HTML endpoint is used rather than a scripted results page because it
    renders links as plain anchors, which is exactly what the run can read and follow.
    """

    return "https://html.duckduckgo.com/html/?q=" + quote_plus(prompt.strip()[:200])


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
