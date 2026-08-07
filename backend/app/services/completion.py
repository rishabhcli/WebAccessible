from __future__ import annotations

from uuid import UUID

from backend.app.browser.controller import BrowserController
from backend.app.contracts.models import VerificationPredicate, VerificationType


class CompletionService:
    def __init__(self, browser: BrowserController, terminal_predicate: str) -> None:
        self.browser = browser
        self.terminal_predicate = terminal_predicate

    async def completed(self, session_id: UUID) -> bool:
        return await self.browser.verify(
            session_id,
            VerificationPredicate(
                type=VerificationType.SAFE_TERMINAL_REACHED,
                value=self.terminal_predicate,
            ),
        )
