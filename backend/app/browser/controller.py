from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any
from uuid import UUID, uuid4

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from backend.app.browser.candidate_extractor import EXTRACT_CANDIDATES_SCRIPT
from backend.app.browser.highlighter import CLEAR_HIGHLIGHT_SCRIPT, HIGHLIGHT_SCRIPT
from backend.app.browser.observer import INSTALL_OBSERVER_SCRIPT
from backend.app.browser.sanitizer import origin_and_path, redact_payload
from backend.app.browser.verifier import verify_predicate
from backend.app.contracts.models import (
    BrowserSessionView,
    ElementCandidate,
    EventEnvelope,
    EventType,
    VerificationPredicate,
)
from backend.app.persistence.repository import OperationalRepository

EventSink = Callable[[EventEnvelope], Awaitable[None]]


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class BrowserController:
    """Observe/highlight/verify-only bridge for managed Browserbase sessions."""

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
                raise RuntimeError("Browserbase did not return a managed session and CDP endpoint")

            try:
                live_view_url = await self._maybe_await(self.adapter.get_live_view(provider_id))
                playwright = await async_playwright().start()
                browser = await playwright.chromium.connect_over_cdp(str(connect_url))
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
                await self.snapshot(web_session_id)
            except Exception:
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

    async def snapshot(self, web_session_id: UUID) -> list[ElementCandidate]:
        runtime = self._require(web_session_id)
        raw = await runtime.page.evaluate(EXTRACT_CANDIDATES_SCRIPT)
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
        return bool(await runtime.page.evaluate(HIGHLIGHT_SCRIPT, candidate_id))

    async def clear_highlight(self, web_session_id: UUID) -> None:
        runtime = self._require(web_session_id)
        await runtime.page.evaluate(CLEAR_HIGHLIGHT_SCRIPT)

    async def verify(self, web_session_id: UUID, predicate: VerificationPredicate) -> bool:
        runtime = self._require(web_session_id)
        return await verify_predicate(runtime.page, predicate)

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
            if not isinstance(payload, dict) or payload.get("trusted") is not True:
                return
            await self._emit_page_event(runtime, page, redact_payload(payload))

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
                asyncio.create_task(self._emit_navigation(runtime, page))

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

    def _require(self, web_session_id: UUID) -> BrowserRuntime:
        runtime = self._runtimes.get(web_session_id)
        if runtime is None:
            raise KeyError(f"no attached Browserbase session for {web_session_id}")
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
