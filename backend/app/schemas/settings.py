"""Pydantic schemas for user trading settings API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

RiskProfile = Literal["conservative", "moderate", "aggressive", "custom"]
ThemePreference = Literal["dark", "light", "system"]


class TradingSettingsOut(BaseModel):
    auto_execution_threshold: float = 85.0
    risk_profile: RiskProfile = "moderate"
    max_risk_per_trade_pct: float = 3.0
    max_positions: int = 10
    theme_preference: ThemePreference = "dark"

    model_config = {"from_attributes": True}


class TradingSettingsPatch(BaseModel):
    auto_execution_threshold: Optional[float] = Field(default=None, ge=0, le=100)
    risk_profile: Optional[RiskProfile] = None
    max_risk_per_trade_pct: Optional[float] = Field(default=None, ge=0.5, le=10)
    max_positions: Optional[int] = Field(default=None, ge=1, le=50)
    theme_preference: Optional[ThemePreference] = None


class PaperBalancePatch(BaseModel):
    balance: float = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class PaperBalanceAuditOut(BaseModel):
    id: str
    previous_balance: float
    new_balance: float
    reason: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
