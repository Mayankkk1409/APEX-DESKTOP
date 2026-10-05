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
    # Client calls POST /auth/refresh this many seconds before access-token exp.
    # Does not extend the access token. 900s lifetime refreshes at 840s.
    access_token_refresh_skew_seconds: int = 60
    refresh_token_ttl_seconds: int = 604800
    # Refresh cookie. Secure stays on in every environment: browsers reject it on
    # insecure hosts other than localhost, where MDN allows the Secure attribute.
    # SameSite=Strict is the OWASP preference for a session cookie. The dev server
    # proxies API calls same-origin, so Strict cookies are still sent on refresh.
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "strict"
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
    #: Host only. The SDK appends paths such as ``/snapTrade/registerUser``.
    #: A trailing ``/api/v1`` is stripped so it is not doubled.
    snaptrade_base_url: str = ""
    encryption_key: str = ""
    api_public_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"

    default_symbol: str = "SPX"
    splash_duration_ms: int = Field(default=3000, ge=2500, le=3500)

    # Rule 1 theta: per-share absolute decay, or decay as a fraction of premium.
    theta_filter_mode: Literal["abs_per_share", "pct_of_premium"] = "pct_of_premium"
    theta_max_pct_per_day: float = 0.015
    # New entries require a higher composite than exits so a score near one line does not flip.
    exit_composite_min: float = 40.0
    entry_composite_min: float = 45.0
    # Front-week IV minus back-week IV, in volatility points (35% vs 30% is 5).
    min_iv_inversion_pts: float = 5.0

    # Rule 1 buy. Theta percent replaces the 1.5% cap for this rule only.
    # Sentiment lines match the existing pillars: score_0_100 >= 65 is the actionable
    # bullish line, and score_0_100 <= 40 is the existing Bearish band (signed <= -20).
    rule1_delta_min: float = 0.55
    rule1_dte_min: int = 30
    rule1_dte_max: int = 90
    rule1_theta_pct_per_day: float = 0.010
    rule1_delta_theta_ratio_min: float = 10.0
    rule1_spread_max: float = 0.08
    rule1_sentiment_bull_min: float = 65.0
    rule1_sentiment_bear_max: float = 40.0

    # Rule 2 sell. Defined risk only.
    rule2_iv_rank_min: float = 50.0
    rule2_rsi_min: float = 40.0
    rule2_rsi_max: float = 60.0
    rule2_short_delta_max: float = 0.20
    rule2_dte_min: int = 30
    rule2_dte_max: int = 45
    rule2_wing_width_pct: float = 0.03
    rule2_spread_max: float = 0.10
    rule2_credit_min_pct_of_width: float = 0.20

    # Gamma Trampoline earnings gates.
    gamma_earnings_days_min: int = 5
    gamma_earnings_days_max: int = 10
    gamma_front_iv_rank_min: float = 70.0
    gamma_front_back_iv_ratio_min: float = 1.25
    gamma_history_hits_min: int = 5
    gamma_history_lookback: int = 8
    gamma_adv_min: float = 5_000_000
    gamma_open_interest_min: int = 1000
    gamma_spread_max: float = 0.08
    gamma_back_week_days: int = 14
    gamma_back_week_tolerance_days: int = 4

    @field_validator("entry_composite_min")
    @classmethod
    def entry_above_exit(cls, value: float, info):  # type: ignore[no-untyped-def]
        exit_min = float((info.data or {}).get("exit_composite_min", 40.0))
        if float(value) <= exit_min:
            raise ValueError("ENTRY_COMPOSITE_MIN must be greater than EXIT_COMPOSITE_MIN")
        return value

    @field_validator("access_token_refresh_skew_seconds")
    @classmethod
    def refresh_skew_before_expiry(cls, value: int, info):  # type: ignore[no-untyped-def]
        if value < 0:
            raise ValueError("access_token_refresh_skew_seconds must be >= 0")
        ttl = int((info.data or {}).get("access_token_ttl_seconds", 900))
        if value >= ttl:
            raise ValueError("access_token_refresh_skew_seconds must be less than access_token_ttl_seconds")
        return value

    @field_validator("cookie_samesite")
    @classmethod
    def samesite_none_requires_secure(cls, value: str, info):  # type: ignore[no-untyped-def]
        secure = bool((info.data or {}).get("cookie_secure", True))
        if value == "none" and not secure:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE")
        return value

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

    @staticmethod
    def _normalize_host(url: str, suffixes: tuple[str, ...]) -> str:
        """Strip a trailing slash and one accidental API prefix.

        Callers append versioned paths themselves (Alpaca ``/v2/...``, SnapTrade
        ``/snapTrade/...``). A base that already ends in that prefix produces a
        doubled URL.
        """
        cleaned = url.strip().rstrip("/")
        lowered = cleaned.lower()
        for suffix in sorted(suffixes, key=len, reverse=True):
            if lowered.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].rstrip("/")
                break
        return cleaned

    @property
    def resolved_broker_base_url(self) -> str:
        if self.alpaca_broker_base_url:
            return self._normalize_host(self.alpaca_broker_base_url, ("/v2",))
        if self.alpaca_trading_mode == "live":
            return "https://api.alpaca.markets"
        return "https://paper-api.alpaca.markets"

    @property
    def resolved_data_base_url(self) -> str:
        raw = self.alpaca_data_base_url or "https://data.alpaca.markets"
        return self._normalize_host(raw, ("/v1beta1", "/v2", "/v1"))

    @property
    def resolved_snaptrade_host(self) -> str:
        raw = self.snaptrade_base_url.strip() or "https://api.snaptrade.com"
        return self._normalize_host(raw, ("/api/v1", "/api/v2"))

    @property
    def snaptrade_configured(self) -> bool:
        return bool(self.snaptrade_client_id.strip() and self.snaptrade_consumer_key.strip() and self.encryption_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
