from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.browser.candidate_extractor import EXTRACT_CANDIDATES_SCRIPT
from backend.app.browser.highlighter import CLEAR_HIGHLIGHT_SCRIPT, HIGHLIGHT_SCRIPT
from backend.app.browser.observer import INSTALL_OBSERVER_SCRIPT
from backend.app.browser.sanitizer import origin_and_path, redact_payload
from backend.app.browser.verifier import verify_predicate
from backend.app.contracts.models import (
    AgentActionKind,
    BrowserSessionView,
    ElementCandidate,
    EventEnvelope,
    EventType,
    VerificationPredicate,
)
from backend.app.persistence.repository import OperationalRepository

EventSink = Callable[[EventEnvelope], Awaitable[None]]

_TARGETED_ACTIONS = frozenset(
    {
        AgentActionKind.CLICK,
        AgentActionKind.FILL,
        AgentActionKind.SELECT,
        AgentActionKind.CHECK,
        AgentActionKind.PRESS,
    }
)


class ProviderBlockedSite(RuntimeError):
    """The execution provider replaced the requested site with a refusal page."""


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """The result of one attempted page action."""

    performed: bool
    failure: str | None
    attempted_at: datetime
    origin: str | None = None
    redacted_path: str | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class PageState:
    """What the browser chrome shows about the current page."""

    origin: str
    redacted_path: str
    title: str | None = None
    # True when the managed browser refused the destination and is showing its own
    # interstitial instead of the requested site.
    blocked: bool = False


# Browserbase serves this page when its navigation policy refuses a destination. It is a
# real, scrapeable page on the provider's own domain, so without this check the agent
# happily plans clicks against Browserbase's marketing navigation.
_PROVIDER_BLOCK_HOSTS = frozenset({"browserbase.com", "www.browserbase.com"})
_PROVIDER_BLOCK_MARKERS = ("navigation-blocked", "navigation_blocked")


def is_provider_block(url: str, title: str | None = None) -> bool:
    """Whether the managed browser is showing its own navigation-refused interstitial."""

    parsed = urlsplit(url)
    if parsed.netloc.lower() in _PROVIDER_BLOCK_HOSTS and any(
        marker in parsed.path.lower() for marker in _PROVIDER_BLOCK_MARKERS
    ):
        return True
    return title is not None and "navigation blocked" in title.casefold()


async def _title(page: Page) -> str | None:
    try:
        value = await page.title()
    except Exception:
        return None
    return value.strip()[:180] or None


def _is_navigation_race(error: Exception) -> bool:
    """Whether a Playwright failure was caused by the page navigating underneath us."""

    text = str(error)
    return (
        "Execution context was destroyed" in text
        or "Cannot find context with specified id" in text
        or "Target closed" in text
        or "frame was detached" in text
    )


def _action_failure(error: Exception) -> str:
    text = str(error).splitlines()[0] if str(error) else type(error).__name__
    if "strict mode violation" in text:
        return "that target matched more than one thing on the page"
    if "not visible" in text or "not enabled" in text:
        return "that target was not ready to use"
    return "the page did not accept that action"


@dataclass
class BrowserRuntime:
    web_session_id: UUID
    user_id: str
    provider_session_id: str
    connect_url: str
    live_view_url: str
    start_url: str
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    page_id: str = field(default_factory=lambda: str(uuid4()))
    page_instance_id: UUID = field(default_factory=uuid4)
    sequence_no: int = 0
    selector_cache: dict[str, str] = field(default_factory=dict)
    io_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active_callbacks: int = 0
    callbacks_idle: asyncio.Event = field(default_factory=asyncio.Event)
    navigation_handler: Callable[[Any], None] | None = None
    event_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class BrowserController:
    """Observe and act through the selected isolated browser execution provider."""

    def __init__(
        self,
        *,
        adapter: Any,
        repository: OperationalRepository,
        event_sink: EventSink | None = None,
    ) -> None:
        self.adapter = adapter
        self.repository = repository
        self.event_sink = event_sink
        self._runtimes: dict[UUID, BrowserRuntime] = {}
        self._lock = asyncio.Lock()

    def set_event_sink(self, sink: EventSink) -> None:
        self.event_sink = sink

    async def start(
        self, *, web_session_id: UUID, user_id: str, start_url: str
    ) -> BrowserSessionView:
        async with self._lock:
            existing = self._runtimes.get(web_session_id)
            if existing:
                return self._view(existing)

            created = await self._maybe_await(
                self.adapter.create_session(
                    start_url=start_url,
                    metadata={
                        "webaccessible_session_id": str(web_session_id),
                        "surface": "participant",
                    },
                )
            )
            provider_id = str(self._value(created, "id", "session_id"))
            connect_url = self._value(created, "connect_url", "connectUrl")
            if not connect_url:
                connect_data = await self._maybe_await(self.adapter.connect_data(provider_id))
                connect_url = self._value(connect_data, "connect_url", "connectUrl", "cdp_url")
            if not provider_id or not connect_url:
                if provider_id:
                    await self._maybe_await(self.adapter.terminate(provider_id))
                raise RuntimeError("The browser provider did not return a session and CDP endpoint")

            playwright: Playwright | None = None
            browser: Browser | None = None
            try:
                live_view_url = await self._maybe_await(self.adapter.get_live_view(provider_id))
                playwright = await async_playwright().start()
                connector = getattr(self.adapter, "connect_browser", None)
                if connector is None:
                    browser = await playwright.chromium.connect_over_cdp(str(connect_url))
                else:
                    browser = await self._maybe_await(connector(playwright, created))
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()
                runtime = BrowserRuntime(
                    web_session_id=web_session_id,
                    user_id=user_id,
                    provider_session_id=provider_id,
                    connect_url=str(connect_url),
                    live_view_url=str(live_view_url),
                    start_url=start_url,
                    playwright=playwright,
                    browser=browser,
                    context=context,
                    page=page,
                )
                self._runtimes[web_session_id] = runtime
                await self._install_page(runtime, page)
                if page.url != start_url:
                    await page.goto(start_url, wait_until="domcontentloaded", timeout=45_000)
                    # Give a client-side redirect a chance to land before observing.
                    try:
                        await page.wait_for_load_state("load", timeout=15_000)
                    except Exception:
                        pass
                await self.snapshot(web_session_id)
                state = await self.page_state(web_session_id)
                if state.blocked:
                    raise ProviderBlockedSite("the browser provider refused the requested site")
            except Exception:
                failed_runtime = self._runtimes.pop(web_session_id, None)
                if failed_runtime is not None:
                    try:
                        await failed_runtime.browser.close()
                    except Exception:
                        pass
                    try:
                        await failed_runtime.playwright.stop()
                    except Exception:
                        pass
                else:
                    if browser is not None:
                        try:
                            await browser.close()
                        except Exception:
                            pass
                    if playwright is not None:
                        try:
                            await playwright.stop()
                        except Exception:
                            pass
                await self._maybe_await(self.adapter.terminate(provider_id))
                raise

            self.repository.save_browser_session(
                web_session_id=web_session_id,
                provider_session_id=provider_id,
                start_url=start_url,
                status="connected",
            )
            self.repository.update_browser_session(web_session_id, status="connected")
            return self._view(runtime)

    async def live_view(self, web_session_id: UUID) -> str:
        runtime = self._require(web_session_id)
        return runtime.live_view_url

    async def screenshot(self, provider_session_id: str) -> bytes:
        """Capture the current local-browser frame for the development Live View."""

        runtime = next(
            (
                item
                for item in self._runtimes.values()
                if item.provider_session_id == provider_session_id
            ),
            None,
        )
        if runtime is None:
            raise KeyError(f"no attached browser session {provider_session_id}")
        async with runtime.io_lock:
            return await runtime.page.screenshot(type="png", animations="disabled")

    async def snapshot(self, web_session_id: UUID) -> list[ElementCandidate]:
        runtime = self._require(web_session_id)
        raw = await self._evaluate_settled(runtime.page, EXTRACT_CANDIDATES_SCRIPT)
        candidates: list[ElementCandidate] = []
        selector_cache: dict[str, str] = {}
        for item in raw or []:
            try:
                candidate = ElementCandidate.model_validate(item["candidate"])
            except (KeyError, ValueError):
                continue
            candidates.append(candidate)
            selector_cache[candidate.candidate_id] = str(item.get("css_path") or "")
        runtime.selector_cache = selector_cache
        return candidates

    async def highlight(self, web_session_id: UUID, candidate_id: str) -> bool:
        runtime = self._require(web_session_id)
        try:
            return bool(await runtime.page.evaluate(HIGHLIGHT_SCRIPT, candidate_id))
        except Exception as error:
            if _is_navigation_race(error):
                return False
            raise

    async def clear_highlight(self, web_session_id: UUID) -> None:
        runtime = self._require(web_session_id)
        await runtime.page.evaluate(CLEAR_HIGHLIGHT_SCRIPT)

    async def verify(self, web_session_id: UUID, predicate: VerificationPredicate) -> bool:
        runtime = self._require(web_session_id)
        return await verify_predicate(runtime.page, predicate)

    async def act(
        self,
        web_session_id: UUID,
        *,
        action: AgentActionKind,
        candidate_id: str | None = None,
        value: str | None = None,
        url: str | None = None,
        timeout_ms: int = 15_000,
    ) -> ActionOutcome:
        """Perform one bounded action on the managed page.

        Targets are addressed through the CSS path captured in the same snapshot the
        planner reasoned over, so an action can only land on an element that was actually
        offered to it. A stale target fails rather than falling back to a guess.
        """

        runtime = self._require(web_session_id)
        page = runtime.page
        started = datetime.now(UTC)
        selector: str | None = None
        if action in _TARGETED_ACTIONS:
            if not candidate_id:
                return ActionOutcome(False, "no target was supplied for this action", started)
            selector = runtime.selector_cache.get(candidate_id)
            if not selector:
                return ActionOutcome(False, "the target is no longer on the page", started)
        try:
            if action is AgentActionKind.CLICK:
                assert selector is not None
                await page.click(selector, timeout=timeout_ms)
            elif action is AgentActionKind.FILL:
                assert selector is not None
                await page.fill(selector, value or "", timeout=timeout_ms)
            elif action is AgentActionKind.SELECT:
                assert selector is not None
                await page.select_option(selector, value or "", timeout=timeout_ms)
            elif action is AgentActionKind.CHECK:
                assert selector is not None
                await page.check(selector, timeout=timeout_ms)
            elif action is AgentActionKind.PRESS:
                assert selector is not None
                await page.press(selector, value or "Enter", timeout=timeout_ms)
            elif action is AgentActionKind.NAVIGATE:
                if not url:
                    return ActionOutcome(False, "no address was supplied", started)
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            elif action is AgentActionKind.SCROLL:
                await page.mouse.wheel(0, 600)
            elif action is AgentActionKind.WAIT:
                await page.wait_for_timeout(min(timeout_ms, 5_000))
            else:  # pragma: no cover - the enum is exhaustive
                return ActionOutcome(False, f"unsupported action {action}", started)
        except PlaywrightTimeoutError:
            return ActionOutcome(False, "the page did not respond to that action in time", started)
        except Exception as error:
            return ActionOutcome(False, _action_failure(error), started)

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            # A same-page interaction never changes load state; that is not a failure.
            pass
        origin, path = origin_and_path(page.url)
        return ActionOutcome(
            True,
            None,
            started,
            origin=origin,
            redacted_path=path,
            title=await _title(page),
        )

    async def page_state(self, web_session_id: UUID) -> PageState:
        """Return the chrome-visible page state: title, origin, redacted path, blocked."""

        runtime = self._require(web_session_id)
        page = runtime.page
        origin, path = origin_and_path(page.url)
        title = await _title(page)
        return PageState(
            origin=origin,
            redacted_path=path,
            title=title,
            blocked=is_provider_block(page.url, title),
        )

    async def go_back(self, web_session_id: UUID) -> bool:
        runtime = self._require(web_session_id)
        try:
            response = await runtime.page.go_back(wait_until="domcontentloaded", timeout=20_000)
        except Exception:
            return False
        return response is not None

    async def current_page_identity(self, web_session_id: UUID) -> tuple[str, UUID, str, str]:
        runtime = self._require(web_session_id)
        origin, path = origin_and_path(runtime.page.url)
        return runtime.page_id, runtime.page_instance_id, origin, path

    def css_path(self, web_session_id: UUID, candidate_id: str) -> str | None:
        return self._require(web_session_id).selector_cache.get(candidate_id) or None

    async def stop(self, web_session_id: UUID, reason: str) -> bool:
        async with self._lock:
            runtime = self._runtimes.pop(web_session_id, None)
            if runtime is None:
                row = self.repository.get_browser_session(web_session_id)
                if not row or row["status"] == "stopped":
                    return True
                provider_id = str(row["provider_session_id"])
            else:
                provider_id = runtime.provider_session_id
                await runtime.callbacks_idle.wait()
                if runtime.navigation_handler is not None:
                    runtime.page.remove_listener("framenavigated", runtime.navigation_handler)
                if runtime.event_tasks:
                    await asyncio.gather(*runtime.event_tasks, return_exceptions=True)
                async with runtime.io_lock:
                    try:
                        await runtime.browser.close()
                    except Exception:
                        pass
                    try:
                        await runtime.playwright.stop()
                    except Exception:
                        pass
            try:
                stopped = bool(await self._maybe_await(self.adapter.terminate(provider_id)))
            except Exception:
                self.repository.update_browser_session(
                    web_session_id, status="termination_failed", terminal_reason=reason
                )
                return False
            self.repository.update_browser_session(
                web_session_id,
                status="stopped" if stopped else "termination_failed",
                terminal_reason=reason,
            )
            return stopped

    async def stop_all(self, reason: str = "backend_shutdown") -> None:
        for session_id in list(self._runtimes):
            await self.stop(session_id, reason)

    async def _install_page(self, runtime: BrowserRuntime, page: Page) -> None:
        async def emit(_source: Any, payload: Any) -> None:
            if runtime.active_callbacks == 0:
                runtime.callbacks_idle.clear()
            runtime.active_callbacks += 1
            try:
                if not isinstance(payload, dict) or payload.get("trusted") is not True:
                    return
                await self._emit_page_event(runtime, page, redact_payload(payload))
            finally:
                runtime.active_callbacks -= 1
                if runtime.active_callbacks == 0:
                    runtime.callbacks_idle.set()

        runtime.callbacks_idle.set()
        try:
            await page.expose_binding("__webaccessibleEmit", emit)
        except Exception as error:
            if "already been registered" not in str(error):
                raise
        await page.add_init_script(f"({INSTALL_OBSERVER_SCRIPT})()")
        await page.evaluate(INSTALL_OBSERVER_SCRIPT)

        def navigation(frame: Any) -> None:
            if frame == page.main_frame:
                runtime.page_instance_id = uuid4()
                runtime.sequence_no = 0
                task = asyncio.create_task(self._emit_navigation(runtime, page))
                runtime.event_tasks.add(task)
                task.add_done_callback(runtime.event_tasks.discard)

        runtime.navigation_handler = navigation
        page.on("framenavigated", navigation)

    async def _emit_navigation(self, runtime: BrowserRuntime, page: Page) -> None:
        if not self.event_sink:
            return
        try:
            await self.snapshot(runtime.web_session_id)
            origin, path = origin_and_path(page.url)
            runtime.sequence_no += 1
            await self.event_sink(
                EventEnvelope(
                    session_id=runtime.web_session_id,
                    user_id=runtime.user_id,
                    browserbase_session_id=runtime.provider_session_id,
                    page_id=runtime.page_id,
                    page_instance_id=runtime.page_instance_id,
                    sequence_no=runtime.sequence_no,
                    origin=origin,
                    redacted_path=path,
                    event_type=EventType.NAVIGATION_OBSERVED,
                    payload={"productive": True},
                )
            )
        except Exception:
            return

    async def _emit_page_event(
        self, runtime: BrowserRuntime, page: Page, payload: dict[str, Any]
    ) -> None:
        if not self.event_sink:
            return
        origin, path = origin_and_path(page.url)
        runtime.sequence_no += 1
        kind = payload.get("kind")
        event_type = EventType.INTERACTION_OBSERVED
        if kind == "activation":
            event_type = EventType.USER_ACTION_OBSERVED
            candidates = await self.snapshot(runtime.web_session_id)
            candidate_id = payload.get("candidate_id")
            candidate = next(
                (item for item in candidates if item.candidate_id == candidate_id), None
            )
            if candidate:
                payload["candidate"] = candidate.model_dump(mode="json")
                payload["css_path"] = runtime.selector_cache.get(candidate.candidate_id)
        elif kind == "form_progress":
            event_type = EventType.FORM_PROGRESS_OBSERVED
            payload = {
                "kind": "form_progress",
                "candidate_id": payload.get("candidate_id"),
                "partly_filled": True,
                "dirty": True,
                "trusted": True,
            }
        await self.event_sink(
            EventEnvelope(
                session_id=runtime.web_session_id,
                user_id=runtime.user_id,
                browserbase_session_id=runtime.provider_session_id,
                page_id=runtime.page_id,
                page_instance_id=runtime.page_instance_id,
                sequence_no=runtime.sequence_no,
                origin=origin,
                redacted_path=path,
                event_type=event_type,
                payload=payload,
            )
        )

    @staticmethod
    async def _evaluate_settled(page: Page, script: str, attempts: int = 4) -> Any:
        """Evaluate a script, tolerating a navigation that lands mid-evaluation.

        Real sites redirect after `domcontentloaded` — a consent interstitial, a store
        locator bounce, an auth hop. Each one destroys the execution context and kills an
        in-flight `evaluate`. Waiting for the new document and retrying is the difference
        between observing a real page and failing to start at all.
        """

        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await page.evaluate(script)
            except Exception as error:
                if not _is_navigation_race(error):
                    raise
                last_error = error
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:
                    pass
                await page.wait_for_timeout(250 * (attempt + 1))
        raise last_error if last_error is not None else RuntimeError("page never settled")

    def _require(self, web_session_id: UUID) -> BrowserRuntime:
        runtime = self._runtimes.get(web_session_id)
        if runtime is None:
            raise KeyError(f"no attached browser session for {web_session_id}")
        return runtime

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        return await value if isawaitable(value) else value

    @staticmethod
    def _value(value: Any, *keys: str) -> Any:
        for key in keys:
            if isinstance(value, dict) and value.get(key) is not None:
                return value[key]
            candidate = getattr(value, key, None)
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _view(runtime: BrowserRuntime) -> BrowserSessionView:
        return BrowserSessionView(
            web_session_id=runtime.web_session_id,
            browserbase_session_id=runtime.provider_session_id,
            live_view_url=runtime.live_view_url,
            status="connected",
            start_url=runtime.start_url,
            created_at=runtime.created_at,
        )
