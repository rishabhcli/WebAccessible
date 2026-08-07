"""Application configuration loaded from environment variables or an ignored .env file."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeMode(StrEnum):
    TEST = "test"
    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed process settings.

    Secrets stay as ``SecretStr`` values so logging or serializing this object does
    not reveal provider credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: RuntimeMode = RuntimeMode.DEVELOPMENT
    app_public_url: AnyHttpUrl = AnyHttpUrl("http://localhost:5173")
    api_public_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    session_signing_secret: SecretStr | None = None
    operational_database_path: Path = Path("data/webaccessible.sqlite3")
    build_commit: str = "local-development"

    demo_target_name: str = "Get in line at the DMV"
    demo_target_url: AnyHttpUrl = AnyHttpUrl(
        "https://mt-cadmvoas.us.qmatic.cloud/branches"
    )
    demo_fallback_url: AnyHttpUrl = AnyHttpUrl("https://booksy.com/en-us/s/haircut")

    browser_execution_provider: Literal["local", "browserbase"] = "local"
    local_browser_headless: bool = True
    browserbase_api_key: SecretStr | None = None
    browserbase_region: Literal["us-west-2", "us-east-1", "eu-central-1", "ap-southeast-1"] = (
        "us-west-2"
    )
    browserbase_session_timeout_seconds: int = Field(default=900, ge=60, le=21600)
    browserbase_request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    browserbase_keep_alive: bool = False
    browserbase_record_session: bool = True
    browserbase_log_session: bool = True

    everos_api_key: SecretStr | None = None
    everos_host: str | None = None
    everos_app_id: str = "default"
    everos_project_id: str = "default"
    everos_timeout_seconds: float = Field(default=60.0, gt=0, le=300)

    snowflake_account: str | None = None
    snowflake_user: str | None = None
    snowflake_password: SecretStr | None = None
    snowflake_role: str | None = None
    snowflake_warehouse: str | None = None
    snowflake_database: str | None = None
    snowflake_schema: str | None = None
    snowflake_login_timeout_seconds: int = Field(default=30, gt=0, le=120)
    snowflake_network_timeout_seconds: int = Field(default=60, gt=0, le=300)
    snowflake_max_connections: int = Field(default=4, ge=1, le=32)
    snowflake_connection_max_idle_seconds: float = Field(default=240.0, gt=0, le=3600)

    readiness_cache_seconds: float = Field(default=10.0, ge=0, le=120)
    routine_cache_seconds: float = Field(default=20.0, ge=0, le=300)

    recall_model: str = "claude-haiku-4-5"
    recall_cache_seconds: float = Field(default=15.0, ge=0, le=300)
    recall_embedding_model: str = "snowflake-arctic-embed-m-v1.5"

    autopilot_max_steps: int = Field(default=24, ge=1, le=120)
    proactive_scan_interval_seconds: float = Field(default=60.0, ge=5, le=3600)
    proactive_max_overdue_intervals: float = Field(default=3.0, ge=1, le=12)

    action_planner_provider: Literal["local", "snowflake_cortex"] = "local"
    guidance_model_provider: Literal["snowflake_cortex"] = "snowflake_cortex"
    guidance_model: str = "claude-haiku-4-5"
    guidance_model_rate_card_version: str = "snowflake-cortex-any-region-2026-08-07"
    guidance_model_max_tokens: int = Field(default=512, ge=64, le=8192)
    guidance_model_prompt_max_chars: int = Field(default=20000, ge=1000, le=100000)
    guidance_model_temperature: float = Field(default=0.0, ge=0, le=1)
    guidance_model_guardrails: bool = True

    escalation_webhook_url: AnyHttpUrl | None = None

    @field_validator(
        "demo_target_name",
        "everos_app_id",
        "everos_project_id",
        "guidance_model",
        "guidance_model_rate_card_version",
        "recall_model",
        "recall_embedding_model",
    )
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def cloud_execution_is_required_outside_local_development(self) -> Settings:
        if self.app_env in {RuntimeMode.DEMO, RuntimeMode.PRODUCTION}:
            if self.browser_execution_provider != "browserbase":
                raise ValueError("demo and production require Browserbase browser execution")
            if self.action_planner_provider != "snowflake_cortex":
                raise ValueError("demo and production require Snowflake Cortex action planning")
        return self

    @property
    def local_browser_enabled(self) -> bool:
        return self.browser_execution_provider == "local"

    @property
    def browserbase_configured(self) -> bool:
        return self.browserbase_api_key is not None

    @property
    def everos_configured(self) -> bool:
        return self.everos_api_key is not None

    @property
    def snowflake_configured(self) -> bool:
        return all(
            (
                self.snowflake_account,
                self.snowflake_user,
                self.snowflake_password,
                self.snowflake_role,
                self.snowflake_warehouse,
                self.snowflake_database,
                self.snowflake_schema,
            )
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings snapshot."""

    return Settings()


def clear_settings_cache() -> None:
    """Refresh settings after process environment changes."""

    get_settings.cache_clear()
