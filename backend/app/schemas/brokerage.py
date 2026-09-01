from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PortalUrlRequest(BaseModel):
    broker: str | None = None


class PortalUrlResponse(BaseModel):
    url: str


class BrokerageAccountOut(BaseModel):
    id: str
    account_name: str
    account_type: str
    broker_name: str
    account_number_masked: str
    sync_status: str
    last_synced_at: datetime | None = None


class AccountBalanceOut(BaseModel):
    cash_balance: float
    buying_power: float
    total_equity: float
    day_pnl: float | None = None
    currency: str
    as_of_timestamp: datetime


class PositionOut(BaseModel):
    symbol: str
    quantity: float
    average_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    currency: str = "USD"


class AccountsResponse(BaseModel):
    connection_status: str | None = None
    accounts: list[BrokerageAccountOut]


class SyncResponse(BaseModel):
    ok: bool = True
    connection_status: str
    account_count: int


class PositionsResponse(BaseModel):
    positions: list[PositionOut]


class OrderOut(BaseModel):
    id: str
    symbol: str
    side: str
    qty: float
    order_type: str
    fill_price: float | None = None
    status: str
    asset_class: str
    created_at: str | None = None
    filled_at: str | None = None


class OrdersResponse(BaseModel):
    orders: list[OrderOut]


class EquityHistoryPoint(BaseModel):
    t: str
    portfolio_value: float
    balance: float | None = None
    cumulative_pl: float | None = None


class EquityHistoryResponse(BaseModel):
    starting_balance: float
    account_mode: str = "real_brokerage"
    points: list[EquityHistoryPoint]


class RegisterUserResponse(BaseModel):
    ok: bool = True
    connection_status: str


class WebhookResponse(BaseModel):
    ok: bool = True


class BrokerageAccountDetail(BrokerageAccountOut):
    balance: AccountBalanceOut | None = None
    positions: list[PositionOut] = Field(default_factory=list)
