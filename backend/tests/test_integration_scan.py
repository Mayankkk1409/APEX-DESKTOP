from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.analysis.layers import DEEP_SCAN_LAYERS, SCAN_SLIDE_LAYERS


async def _auth(client: AsyncClient) -> str:
    await client.post(
        "/auth/signup",
        json={
            "full_name": "Scanner",
            "username": "scanner",
            "email": "scanner@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 50000,
        },
    )
    await client.post("/auth/login", json={"username": "scanner", "password": "ApexDesk!23"})
    otp = await client.post("/auth/otp/request", json={"username": "scanner"})
    verify = await client.post("/auth/otp/verify", json={"username": "scanner", "code": otp.json()["code"]})
    return verify.json()["access_token"]


def test_options_chain_and_greeks_are_one_layer() -> None:
    """Full Document §5 is one section, so the slide is one combined screen."""
    values = [layer.value for layer in DEEP_SCAN_LAYERS]
    assert "options_chain_greeks" in values
    assert "options_chain" not in values
    assert "greeks" not in values
    # Combined layer sits where the pair used to, between support/resistance and volatility.
    assert values.index("support_resistance") < values.index("options_chain_greeks")
    assert values.index("options_chain_greeks") < values.index("volatility")
    assert values[values.index("options_chain_greeks") + 1] == "volatility"
    assert "apex_score" in values
    assert values.index("fundamentals") < values.index("apex_score")
    assert values.index("apex_score") < values.index("strategy")
    assert values.index("strategy") < values.index("risk_review")
    assert len(values) == 17


@pytest.mark.asyncio
async def test_scan_layer_catalog_endpoint_matches_the_enum(client: AsyncClient) -> None:
    res = await client.get("/scan/layers")
    assert res.status_code == 200
    body = res.json()
    assert body["layers"] == [layer.value for layer in DEEP_SCAN_LAYERS]
    assert body["slide_layers"] == list(SCAN_SLIDE_LAYERS)


@pytest.mark.asyncio
async def test_scan_carries_the_selected_expiry_into_the_combined_layer(client: AsyncClient) -> None:
    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    exps = await client.get("/market/expirations/AAPL")
    expiry = exps.json()["expirations"][1]["date"]
    snapshot = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "visible_from": "2026-01-01T00:00:00+00:00",
        "visible_to": datetime.now(timezone.utc).isoformat(),
        "studies": ["EMA_9"],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    scan = await client.post("/scan", json={"snapshot": snapshot, "expiry": expiry}, headers=headers)
    assert scan.status_code == 200, scan.text
    layer = scan.json()["layer_data"]["options_chain_greeks"]

    assert layer["expiry"] == expiry, "the combined layer must use the expiry the session selected"
    assert layer["contracts"], "the demo adapter always returns a chain for a live expiry"
    assert len(layer["cards"]) >= 14
    assert len(layer["cards"]) == len({c["id"] for c in layer["cards"]})
    assert layer["data_source"]["is_live"] is False, "no credentials in test env — must not claim live data"
    assert layer["thresholds"]["min_open_interest"] == 500
    assert all(row["verdict"] is not None for row in layer["contracts"])


@pytest.mark.asyncio
async def test_scan_without_an_expiry_claims_no_chain_analysis(client: AsyncClient) -> None:
    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    snapshot = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "visible_from": "2026-01-01T00:00:00+00:00",
        "visible_to": datetime.now(timezone.utc).isoformat(),
        "studies": ["EMA_9"],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    scan = await client.post("/scan", json={"snapshot": snapshot, "expiry": None}, headers=headers)
    layer = scan.json()["layer_data"]["options_chain_greeks"]
    assert layer["contracts"] == []
    assert layer["cards"][0]["id"] == "chain-unavailable"


@pytest.mark.asyncio
async def test_options_analysis_endpoint(client: AsyncClient) -> None:
    exps = await client.get("/market/expirations/AAPL")
    expiry = exps.json()["expirations"][1]["date"]
    res = await client.get("/market/options/AAPL/analysis", params={"expiry": expiry, "spread_max_pct": 0.15})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expiry"] == expiry
    assert body["thresholds"]["spread_max_pct_of_mid"] == 0.15
    assert "recommendedContract" in body
    # Greek + candidate cards collapse by one when a recommended leg replaces both ranked lists.
    assert 14 <= len(body["cards"]) <= 15
    assert body["data_source"]["is_live"] is False


@pytest.mark.asyncio
async def test_options_analysis_endpoint_rejects_an_out_of_band_spread_cap(client: AsyncClient) -> None:
    res = await client.get("/market/options/AAPL/analysis", params={"expiry": "2026-12-18", "spread_max_pct": 0.9})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_options_analysis_endpoint_survives_a_garbage_expiry(client: AsyncClient) -> None:
    res = await client.get("/market/options/AAPL/analysis", params={"expiry": "whenever"})
    assert res.status_code == 200
    assert res.json()["contracts"] == []


@pytest.mark.asyncio
async def test_scan_layers_risk_order_fill_balance(client: AsyncClient) -> None:
    token = await _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    snapshot = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "visible_from": "2026-01-01T00:00:00+00:00",
        "visible_to": datetime.now(timezone.utc).isoformat(),
        "studies": ["EMA_9", "EMA_21", "EMA_50", "EMA_100", "EMA_200", "MACD", "RSI", "BB", "SUPERTREND"],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    expiries = await client.get("/market/expirations/AAPL", headers=headers)
    expiry = expiries.json()["expirations"][0]["date"]
    scan = await client.post("/scan", json={"snapshot": snapshot, "expiry": expiry}, headers=headers)
    assert scan.status_code == 200, scan.text
    data = scan.json()
    assert data["layers"] == [l.value for l in DEEP_SCAN_LAYERS]
    assert set(data["layer_data"]) == {l.value for l in DEEP_SCAN_LAYERS}
    assert data["layer_data"]["technical"]["snapshot"]["symbol"] == "AAPL"
    assert data["layer_data"]["risk_review"]["requires_checkbox"] is True
    assert data["slide_layers"] == list(SCAN_SLIDE_LAYERS)
    apex = data["layer_data"]["apex_score"]
    assert apex["composite_score"] == data["composite_score"]
    assert [s["id"] for s in apex["sections"]] == [
        "technicals",
        "options",
        "volatility",
        "sentiment",
        "fundamentals",
        "risk",
    ]
    strategy = data["layer_data"]["strategy"]
    assert strategy["selected_strategy"]
    if strategy.get("tradeable"):
        assert strategy["what_is_this"]
        assert strategy["metrics"]["legs"] is not None
    slide_order = ["fundamentals", "apex_score", "strategy", "risk_review"]
    enum_values = [l.value for l in DEEP_SCAN_LAYERS]
    for i in range(len(slide_order) - 1):
        assert enum_values.index(slide_order[i]) < enum_values.index(slide_order[i + 1])

    strategy_legs = data["layer_data"]["risk_review"]["strategy_legs"]
    selected = strategy["selected_strategy"]
    if "NO TRADE" in selected or not strategy.get("tradeable") or not strategy_legs:
        return
    assert strategy_legs
    order = await client.post(
        "/api/orders",
        json={
            "scan_id": data["id"],
            "thesis_accepted": True,
            "asset_class": "us_option",
            "legs": strategy_legs,
            "contracts_per_leg": 1,
        },
        headers=headers,
    )
    assert order.status_code == 200, order.text
    assert order.json()["status"] == "filled"
    assert order.json()["asset_class"] == "us_option"
    positions = await client.get("/api/positions", headers=headers)
    filled_symbols = {leg["symbol"] for leg in strategy_legs}
    assert any(p["symbol"] in filled_symbols and p.get("asset_class") == "us_option" for p in positions.json()["positions"])
