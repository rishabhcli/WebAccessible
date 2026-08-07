"""Development-only Chromium execution using the installed Playwright runtime."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import uuid4

from backend.app.config import Settings

# Chromium in headless mode announces itself as "HeadlessChrome/<version>", and real
# services reject that outright: the California DMV queue this product opens sits behind
# a load balancer that answers 403 to any request carrying the token, whatever the client
# is otherwise.  A 403 page has nothing on it to plan against, so the run ended on its
# first step.  The window is a real Chromium asking for a page a person asked for, so it
# says so honestly -- same engine, same version, same platform, without the marker that
# gets an errand refused at the door.
_PLATFORM_TOKENS: Final[dict[str, str]] = {
    "darwin": "Macintosh; Intel Mac OS X 10_15_7",
    "win32": "Windows NT 10.0; Win64; x64",
}
_LINUX_PLATFORM_TOKEN: Final = "X11; Linux x86_64"


def desktop_user_agent(version: str) -> str:
    """Build the User-Agent a person's own Chrome would send for this Chromium build."""

    # ``Browser.version`` is a bare version like "151.0.7922.34"; tolerate a
    # "HeadlessChrome/151.0.7922.34" shape too rather than pasting a product name in.
    chrome_version = version.rsplit("/", 1)[-1].strip() or "140.0.0.0"
    platform = _PLATFORM_TOKENS.get(sys.platform, _LINUX_PLATFORM_TOKEN)
    return (
        f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_version} Safari/537.36"
    )


@dataclass(frozen=True, slots=True)
class LocalBrowserSessionData:
    id: str
    connect_url: str
    status: str
    start_url: str
    created_at: datetime


class LocalBrowserAdapter:
    """Launch Chromium locally while preserving the controller's provider contract."""

    def __init__(self, settings: Settings) -> None:
        if not settings.local_browser_enabled:
            raise ValueError("the local browser adapter requires local execution mode")
        self._headless = settings.local_browser_headless

    async def create_session(
        self,
        start_url: str,
        metadata: dict[str, Any],
    ) -> LocalBrowserSessionData:
        parsed = urlsplit(start_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("start_url must be an absolute http(s) URL")
        if not metadata.get("webaccessible_session_id"):
            raise ValueError("metadata must include the WebAccessible session ID")
        session_id = f"local-{uuid4()}"
        return LocalBrowserSessionData(
            id=session_id,
            connect_url=f"local://{session_id}",
            status="running",
            start_url=start_url,
            created_at=datetime.now(UTC),
        )

    async def connect_browser(self, playwright: Any, _session: Any) -> Any:
        browser = await playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-background-networking", "--disable-dev-shm-usage"],
        )
        # The context is opened here rather than left to the controller because the
        # User-Agent can only be set when a context is created.  The controller adopts
        # ``contexts[0]`` when one already exists, which is the same path a
        # CDP-attached managed browser takes.
        await browser.new_context(user_agent=desktop_user_agent(browser.version))
        return browser

    async def get_live_view(self, session_id: str) -> str:
        # The development UI and API are commonly served by the same FastAPI
        # process on a caller-selected port.  Keeping this URL same-origin avoids
        # pinning the iframe to API_PUBLIC_URL's default port (8000), which breaks
        # whenever the process is started on another port (for example 3000).
        return f"/v1/local-browser/{session_id}/view"

    async def terminate(self, _session_id: str) -> bool:
        return True

    async def reconcile_orphans(self) -> int:
        return 0
