from __future__ import annotations

from uuid import UUID

from backend.app.browser.controller import BrowserController
from backend.app.contracts.models import BrowserSessionView


class BrowserLifecycleService:
    def __init__(self, controller: BrowserController) -> None:
        self.controller = controller

    async def create(self, *, session_id: UUID, user_id: str, start_url: str) -> BrowserSessionView:
        return await self.controller.start(
            web_session_id=session_id, user_id=user_id, start_url=start_url
        )

    async def live_view(self, session_id: UUID) -> str:
        return await self.controller.live_view(session_id)

    async def stop(self, session_id: UUID, reason: str) -> bool:
        return await self.controller.stop(session_id, reason)
