from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from backend.app.browser.controller import BrowserController
from backend.app.config import Settings, get_settings
from backend.app.contracts.models import EventEnvelope
from backend.app.domain.safety import SafetyPolicy
from backend.app.integrations.browserbase import BrowserbaseAdapter
from backend.app.integrations.everos import EverOSAdapter
from backend.app.integrations.local_browser import LocalBrowserAdapter
from backend.app.integrations.model import CortexGuidanceAdapter
from backend.app.integrations.snowflake import SnowflakeAdapter
from backend.app.persistence.repository import OperationalRepository
from backend.app.services.auth import ParticipantAuthService
from backend.app.services.autopilot import AutopilotService, CortexActionPlanner, LocalActionPlanner
from backend.app.services.completion import CompletionService
from backend.app.services.cost_calculator import CostCalculator
from backend.app.services.event_hub import SessionEventHub
from backend.app.services.guidance import GuidanceService
from backend.app.services.orchestrator import SessionOrchestrator
from backend.app.services.proactive import ProactiveReminderScheduler
from backend.app.services.recall import RecallService
from backend.app.services.scam_shield import ScamShieldService
from backend.app.services.telemetry import TelemetryService


class UnavailableAdapter:
    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, operation: str) -> Any:
        async def unavailable(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(f"{self.name} is not configured")

        return unavailable


class AppContainer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.repository = OperationalRepository(str(self.settings.operational_database_path))
        self.auth = ParticipantAuthService(self.settings, self.repository)
        self.snowflake = SnowflakeAdapter(self.settings)
        self.browserbase: Any = (
            BrowserbaseAdapter(self.settings)
            if self.settings.browserbase_configured
            else UnavailableAdapter("Browserbase")
        )
        self.browser_adapter: Any = (
            LocalBrowserAdapter(self.settings)
            if self.settings.local_browser_enabled
            else self.browserbase
        )
        self.everos: Any = (
            EverOSAdapter(self.settings)
            if self.settings.everos_configured
            else UnavailableAdapter("EverOS")
        )
        self.model: Any = (
            CortexGuidanceAdapter(self.settings, self.snowflake)
            if self.settings.snowflake_configured
            else UnavailableAdapter("Snowflake Cortex")
        )
        self.event_hub = SessionEventHub()
        self.browser = BrowserController(adapter=self.browser_adapter, repository=self.repository)
        self.browserbase_authorized = False
        self.guidance = GuidanceService(
            model_adapter=self.model,
            browser=self.browser,
            repository=self.repository,
            safety_policy=SafetyPolicy(),
            model_name=self.settings.guidance_model,
            rate_card_version=self.settings.guidance_model_rate_card_version,
            cost_calculator=CostCalculator(self.snowflake),
            source_environment=self.settings.app_env.value,
            scam_shield=(
                ScamShieldService(self.snowflake)
                if self.settings.snowflake_configured
                else None
            ),
        )
        self.completion = CompletionService(self.browser, "w3c_sandwich_choices_selected")
        self.recall = RecallService(
            everos=self.everos,
            snowflake=self.snowflake,
            repository=self.repository,
            model=self.settings.recall_model,
            cache_seconds=self.settings.recall_cache_seconds,
        )
        self.orchestrator = SessionOrchestrator(
            repository=self.repository,
            browser=self.browser,
            everos=self.everos,
            guidance=self.guidance,
            completion=self.completion,
            event_hub=self.event_hub,
            demo_target_name=self.settings.demo_target_name,
            demo_target_url=str(self.settings.demo_target_url),
            demo_fallback_url=str(self.settings.demo_fallback_url),
            build_commit=self.settings.build_commit,
            source_environment=self.settings.app_env.value,
            recall=self.recall,
            routine_cache_seconds=self.settings.routine_cache_seconds,
            max_overdue_intervals=self.settings.proactive_max_overdue_intervals,
            embedder=self.snowflake if self.settings.snowflake_configured else None,
            embedding_model=self.settings.recall_embedding_model,
        )
        self.autopilot = AutopilotService(
            browser=self.browser,
            planner=(
                LocalActionPlanner()
                if self.settings.action_planner_provider == "local"
                else CortexActionPlanner(
                    self.snowflake,
                    model=self.settings.action_planner_model,
                    max_tokens=self.settings.action_planner_max_tokens,
                    temperature=self.settings.guidance_model_temperature,
                )
            ),
            event_hub=self.event_hub,
            repository=self.repository,
            max_steps=self.settings.autopilot_max_steps,
        )
        self.proactive = ProactiveReminderScheduler(
            orchestrator=self.orchestrator,
            event_hub=self.event_hub,
            scan_interval_seconds=self.settings.proactive_scan_interval_seconds,
        )

        async def handle_browser_event(event: EventEnvelope) -> None:
            await self.orchestrator.handle_event(event)

        self.browser.set_event_sink(handle_browser_event)
        self.telemetry: TelemetryService | None = None
        self._readiness_cache: tuple[float, Any] | None = None
        self._readiness_lock = asyncio.Lock()
        self._background: set[asyncio.Task[Any]] = set()

    def track_background(self, task: asyncio.Task[Any]) -> None:
        """Hold a reference to a fire-and-forget task so it is not garbage collected."""

        self._background.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self._background.discard(done)
            if done.cancelled():
                return
            try:
                done.exception()
            except Exception:
                pass

        task.add_done_callback(finished)

    async def start(self) -> None:
        if (
            self.settings.browser_execution_provider == "browserbase"
            and self.settings.browserbase_configured
        ):
            await self.browserbase.reconcile_orphans()
            self.browserbase_authorized = True
        try:
            self.telemetry = TelemetryService(
                repository=self.repository,
                snowflake=self.snowflake,
                max_concurrency=1,
            )
            await self.telemetry.start()
        except RuntimeError:
            self.telemetry = None
        await self.proactive.start()

    async def cached_readiness(self, build: Callable[[], Awaitable[Any]]) -> Any:
        """Serve readiness from a short cache.

        The app polls readiness every 30 seconds and each probe is a live provider call.
        Caching collapses concurrent and repeated polls into one round of probes.
        """

        ttl = self.settings.readiness_cache_seconds
        if ttl <= 0:
            return await build()
        cached = self._readiness_cache
        if cached is not None and cached[0] > monotonic():
            return cached[1]
        async with self._readiness_lock:
            cached = self._readiness_cache
            if cached is not None and cached[0] > monotonic():
                return cached[1]
            value = await build()
            self._readiness_cache = (monotonic() + ttl, value)
            return value

    async def close(self) -> None:
        await self.proactive.stop()
        await self.browser.stop_all()
        pending = tuple(self._background)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self.telemetry is not None:
            await self.telemetry.stop()
        await self.snowflake.close()
        closer = getattr(self.everos, "close", None)
        if closer is not None:
            try:
                await closer()
            except Exception:
                pass
        self.repository.close()
