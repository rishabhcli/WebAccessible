"""Development-only Chromium execution using the installed Playwright runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from backend.app.config import Settings


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
        self._api_public_url = str(settings.api_public_url).rstrip("/")

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
        return await playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-background-networking", "--disable-dev-shm-usage"],
        )

    async def get_live_view(self, session_id: str) -> str:
        return f"{self._api_public_url}/v1/local-browser/{session_id}/view"

    async def terminate(self, _session_id: str) -> bool:
        return True

    async def reconcile_orphans(self) -> int:
        return 0
