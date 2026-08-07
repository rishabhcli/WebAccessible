from __future__ import annotations

import re
from urllib.parse import urlsplit

from playwright.async_api import Locator, Page

from backend.app.browser.selector_resolver import locator_for
from backend.app.contracts.models import VerificationPredicate, VerificationType


async def verify_predicate(page: Page, predicate: VerificationPredicate) -> bool:
    if predicate.type == VerificationType.URL_PATH_EQUALS:
        return urlsplit(page.url).path.rstrip("/") == predicate.value.rstrip("/")
    if predicate.type == VerificationType.URL_PATH_MATCHES:
        return re.fullmatch(predicate.value, urlsplit(page.url).path) is not None
    if predicate.type == VerificationType.PAGE_TITLE_CONTAINS:
        return predicate.value.casefold() in (await page.title()).casefold()
    if predicate.type == VerificationType.VISIBLE_TEXT_PRESENT:
        return await page.get_by_text(predicate.value, exact=False).count() > 0
    if predicate.type in {VerificationType.ELEMENT_PRESENT, VerificationType.ELEMENT_ABSENT}:
        if not predicate.selector:
            return False
        found = False
        for selector in predicate.selector.selectors:
            locator = await locator_for(page, selector)
            if await locator.count() == 1 and await locator.first.is_visible():
                found = True
                break
        return found if predicate.type == VerificationType.ELEMENT_PRESENT else not found
    if predicate.type == VerificationType.ARIA_STATE_EQUALS:
        if not predicate.selector or not predicate.state_name:
            return False
        selector = predicate.selector.selectors[0]
        locator = await locator_for(page, selector)
        if await locator.count() != 1:
            return False
        state_name = predicate.state_name.removeprefix("aria-")
        actual = await locator.first.get_attribute(f"aria-{state_name}")
        if actual is None and state_name == "checked":
            actual = "true" if await locator.first.is_checked() else "false"
        return (actual or "").casefold() == predicate.value.casefold()
    if predicate.type == VerificationType.SAFE_TERMINAL_REACHED:
        return await _verify_named_terminal(page, predicate.value)
    return False


async def _verify_named_terminal(page: Page, terminal: str) -> bool:
    if terminal == "w3c_sandwich_choices_selected":
        lettuce = page.get_by_role("checkbox", name="Lettuce", exact=True)
        tomato = page.get_by_role("checkbox", name="Tomato", exact=True)
        if await lettuce.count() != 1 or await tomato.count() != 1:
            return False
        return await _checked(lettuce.first) and await _checked(tomato.first)
    if terminal.startswith("text:"):
        return await page.get_by_text(terminal.removeprefix("text:"), exact=False).count() > 0
    return False


async def _checked(locator: Locator) -> bool:
    aria = await locator.get_attribute("aria-checked")
    if aria is not None:
        return aria == "true"
    return await locator.is_checked()
