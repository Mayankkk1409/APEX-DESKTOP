from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _CONFIG_DIR.parent
_PROJECT_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_PROJECT_ROOT / ".env"), str(_BACKEND_DIR / ".env")),
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = "change-me-to-a-long-random-string"
    app_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
    log_level: str = "INFO"
    sentry_dsn: str = ""

    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604800
    otp_ttl_seconds: int = 90
    autofill_2fa: bool = False

    database_url: str = "sqlite+aiosqlite:///./apex.db"
    redis_url: str = "redis://localhost:6379/0"

    alpaca_api_key_id: str = ""
    alpaca_api_secret_key: str = ""
    alpaca_trading_mode: Literal["paper", "live"] = "paper"
    alpaca_broker_base_url: str = ""
    alpaca_data_base_url: str = ""
    #: When false (default), missing keys / empty vendor responses return an empty
    #: chain — never a fabricated Black-Scholes ladder. Opt in only for offline demos.
    allow_options_simulator: bool = False

    snaptrade_client_id: str = ""
    snaptrade_consumer_key: str = ""
    snaptrade_env: str = "sandbox"
    encryption_key: str = ""
    api_public_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"

    default_symbol: str = "SPX"
    splash_duration_ms: int = Field(default=3000, ge=2500, le=3500)

    @field_validator("autofill_2fa")
    @classmethod
    def no_autofill_in_prod(cls, value: bool, info):  # type: ignore[no-untyped-def]
        env = (info.data or {}).get("app_env")
        if env == "production":
            return False
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",") if o.strip()]

    @property
    def alpaca_keys_present(self) -> bool:
        return bool(self.alpaca_api_key_id and self.alpaca_api_secret_key)

    @property
    def resolved_broker_base_url(self) -> str:
        if self.alpaca_broker_base_url:
            return self.alpaca_broker_base_url
        if self.alpaca_trading_mode == "live":
            return "https://api.alpaca.markets"
        return "https://paper-api.alpaca.markets"

    @property
    def resolved_data_base_url(self) -> str:
        if self.alpaca_data_base_url:
            return self.alpaca_data_base_url
        return "https://data.alpaca.markets"


@lru_cache
def get_settings() -> Settings:
    return Settings()
