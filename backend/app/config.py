"""Application configuration loaded from environment variables or an ignored .env file."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
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

    demo_target_name: str = "Choose lettuce and tomato"
    demo_target_url: AnyHttpUrl = AnyHttpUrl(
        "https://www.w3.org/WAI/ARIA/apg/patterns/checkbox/examples/checkbox/"
    )
    demo_fallback_url: AnyHttpUrl = AnyHttpUrl(
        "https://www.w3.org/WAI/ARIA/apg/patterns/radio/examples/radio/"
    )

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
    )
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

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
