from __future__ import annotations

from typing import Any

from backend.app.browser.controller import BrowserController
from backend.app.config import Settings, get_settings
from backend.app.contracts.models import EventEnvelope
from backend.app.domain.safety import SafetyPolicy
from backend.app.integrations.browserbase import BrowserbaseAdapter
from backend.app.integrations.everos import EverOSAdapter
from backend.app.integrations.model import CortexGuidanceAdapter
from backend.app.integrations.snowflake import SnowflakeAdapter
from backend.app.persistence.repository import OperationalRepository
from backend.app.services.auth import ParticipantAuthService
from backend.app.services.completion import CompletionService
from backend.app.services.cost_calculator import CostCalculator
from backend.app.services.event_hub import SessionEventHub
from backend.app.services.guidance import GuidanceService
from backend.app.services.orchestrator import SessionOrchestrator
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
        self.browser = BrowserController(adapter=self.browserbase, repository=self.repository)
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
        )
        self.completion = CompletionService(self.browser, "w3c_sandwich_choices_selected")
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
        )

        async def handle_browser_event(event: EventEnvelope) -> None:
            await self.orchestrator.handle_event(event)

        self.browser.set_event_sink(handle_browser_event)
        self.telemetry: TelemetryService | None = None

    async def start(self) -> None:
        if self.settings.browserbase_configured:
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

    async def close(self) -> None:
        await self.browser.stop_all()
        if self.telemetry is not None:
            await self.telemetry.stop()
        self.repository.close()
