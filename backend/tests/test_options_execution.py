"""Options-only execution and strategy leg fills."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.orders import estimate_order_cost


def test_options_order_cost_uses_contract_multiplier() -> None:
    assert estimate_order_cost(2, 4.50, asset_class="us_option") == 900.0


@pytest.mark.asyncio
async def test_place_order_rejects_equity_without_legs(client: AsyncClient) -> None:
    from tests.test_integration_scan import _auth

    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/api/orders",
        json={
            "symbol": "AAPL",
            "side": "buy",
            "qty": 1,
            "asset_class": "us_equity",
            "thesis_accepted": True,
        },
        headers=headers,
    )
    assert res.status_code == 400
    assert "options-only" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_place_order_fills_strategy_legs(client: AsyncClient) -> None:
    from tests.test_integration_scan import _auth

    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    occ = "AAPL270115C00150000"
    res = await client.post(
        "/api/orders",
        json={
            "thesis_accepted": True,
            "asset_class": "us_option",
            "legs": [{"symbol": occ, "side": "buy", "qty": 1}],
            "contracts_per_leg": 1,
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["asset_class"] == "us_option"
    assert body["legs_filled"][0]["symbol"] == occ
    assert body["legs_filled"][0]["asset_class"] == "us_option"
    positions = await client.get("/api/positions", headers=headers)
    assert any(p["symbol"] == occ and p["asset_class"] == "us_option" for p in positions.json()["positions"])
