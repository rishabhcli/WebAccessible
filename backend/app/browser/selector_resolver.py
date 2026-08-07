from __future__ import annotations

from typing import Any, cast

from playwright.async_api import Locator, Page

from backend.app.contracts.models import SelectorSpec, SelectorType


async def locator_for(page: Page, selector: SelectorSpec) -> Locator:
    if selector.type == SelectorType.ARIA:
        role = cast(Any, selector.role or "button")
        return page.get_by_role(role, name=selector.value, exact=True)
    if selector.type == SelectorType.TEXT:
        return page.get_by_text(selector.value, exact=True)
    return page.locator(selector.value)


async def uniquely_actionable(locator: Locator) -> bool:
    if await locator.count() != 1:
        return False
    target = locator.first
    return await target.is_visible() and await target.is_enabled()
