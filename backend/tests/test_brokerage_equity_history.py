from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services import snaptrade as st
from tests.test_brokerage import _auth_headers


@pytest.mark.asyncio
async def test_equity_history_returns_cached_snapshots(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_eq_hist")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-eq", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    accounts = [{"id": "acc-eq-1", "name": "Main", "number": "55556666", "institution_name": "Alpaca"}]
    now = datetime.now(timezone.utc)
    balances = [
        {"cash_balance": 1000.0, "buying_power": 2000.0, "total_equity": 10000.0, "currency": "USD"},
        {"cash_balance": 1100.0, "buying_power": 2100.0, "total_equity": 11000.0, "currency": "USD"},
        {"cash_balance": 1200.0, "buying_power": 2200.0, "total_equity": 12000.0, "currency": "USD"},
    ]
    call_count = {"n": 0}

    async def balance_side_effect(*_args, **_kwargs):
        idx = min(call_count["n"], len(balances) - 1)
        call_count["n"] += 1
        return balances[idx]

    with (
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
        patch.object(st, "fetch_balance", AsyncMock(side_effect=balance_side_effect)),
        patch.object(st, "fetch_day_pnl", AsyncMock(return_value=25.0)),
    ):
        await client.post("/api/brokerage/sync", headers=headers)
        await client.get("/api/brokerage/accounts/acc-eq-1/balance", headers=headers)
        await client.get("/api/brokerage/accounts/acc-eq-1/balance", headers=headers)

    res = await client.get("/api/brokerage/accounts/acc-eq-1/equity-history", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["account_mode"] == "real_brokerage"
    assert body["starting_balance"] == 10000.0
    assert len(body["points"]) >= 2
    assert body["points"][0]["portfolio_value"] == 10000.0
    assert body["points"][-1]["portfolio_value"] == 12000.0
    assert body["points"][-1]["cumulative_pl"] == 2000.0


@pytest.mark.asyncio
async def test_equity_history_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/brokerage/accounts/acc-eq-1/equity-history")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_orders_endpoint_returns_normalized_rows(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_orders")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-ord", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    accounts = [{"id": "acc-ord-1", "name": "Main", "number": "77778888", "institution_name": "Alpaca"}]
    orders = [
        {
            "brokerage_order_id": "ord-1",
            "universal_symbol": {"symbol": "AAPL"},
            "action": "BUY",
            "filled_quantity": "5",
            "execution_price": "175.25",
            "order_type": "Market",
            "status": {"raw": "EXECUTED"},
            "time_placed": datetime.now(timezone.utc) - timedelta(days=1),
            "time_executed": datetime.now(timezone.utc) - timedelta(days=1),
        }
    ]
    with (
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
        patch.object(st, "fetch_balance", AsyncMock(return_value={"cash_balance": 0, "buying_power": 0, "total_equity": 0, "currency": "USD"})),
        patch.object(st, "fetch_day_pnl", AsyncMock(return_value=None)),
        patch.object(st, "fetch_orders", AsyncMock(return_value=[st._normalize_order(orders[0])])),
    ):
        await client.post("/api/brokerage/sync", headers=headers)
        res = await client.get("/api/brokerage/accounts/acc-ord-1/orders", headers=headers)
    assert res.status_code == 200
    row = res.json()["orders"][0]
    assert row["symbol"] == "AAPL"
    assert row["side"] == "buy"
    assert row["qty"] == 5.0
    assert row["fill_price"] == 175.25


def test_normalize_order_maps_snaptrade_fields() -> None:
    row = {
        "brokerage_order_id": "b-99",
        "universal_symbol": {"symbol": "MSFT"},
        "action": "SELL_SHORT",
        "filled_quantity": "2",
        "execution_price": "420.5",
        "order_type": "Limit",
        "status": {"raw": "EXECUTED"},
        "time_placed": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "time_executed": datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    }
    out = st._normalize_order(row)
    assert out["id"] == "b-99"
    assert out["symbol"] == "MSFT"
    assert out["side"] == "sell"
    assert out["qty"] == 2.0
    assert out["fill_price"] == 420.5
    assert out["status"] == "EXECUTED"
