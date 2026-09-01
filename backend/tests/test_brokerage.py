from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.encryption import decrypt_secret, encrypt_secret
from app.services import snaptrade as st


async def _auth_headers(client: AsyncClient, username: str = "broker1") -> dict[str, str]:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Broker QA",
            "username": username,
            "email": f"{username}@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 10000,
        },
    )
    assert res.status_code == 201
    await client.post("/auth/login", json={"username": username, "password": "ApexDesk!23"})
    otp = await client.post("/auth/otp/request", json={"username": username})
    code = otp.json()["code"]
    verify = await client.post("/auth/otp/verify", json={"username": username, "code": code})
    token = verify.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_encryption_roundtrip() -> None:
    key = "test-encryption-key-32-bytes-long!!"
    enc = encrypt_secret("snap-secret-value", key)
    assert enc != "snap-secret-value"
    assert decrypt_secret(enc, key) == "snap-secret-value"


def test_webhook_signature_valid_and_invalid() -> None:
    payload = {"eventTimestamp": datetime.now(timezone.utc).isoformat(), "userId": "apex-user"}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    digest = hmac.new(b"test-consumer-key", body, hashlib.sha256).digest()
    sig = base64.b64encode(digest).decode()
    assert st.verify_webhook_signature(body, sig)
    assert not st.verify_webhook_signature(body, "bad-signature")


def test_oauth_state_roundtrip() -> None:
    state = st.new_oauth_state("user-123")
    assert st.verify_oauth_state(state) == "user-123"
    assert st.verify_oauth_state("tampered") is None


def test_normalize_balance_total_dict() -> None:
    balance = st._normalize_balance(
        [{"currency": {"code": "USD"}, "cash": 41.18, "buying_power": 41.18}],
        total_equity=8943.52,
    )
    assert balance["total_equity"] == 8943.52
    assert balance["cash_balance"] == 41.18
    assert balance["buying_power"] == 41.18
    assert balance["currency"] == "USD"


def test_normalize_balance_from_account_total() -> None:
    account = {"id": "acc-1", "balance": {"total": {"amount": 25000.0, "currency": "USD"}}}
    balance_rows = [{"currency": {"code": "USD"}, "cash": 1234.56, "buying_power": 5000.0}]
    assert st._total_equity_from_account(account) == 25000.0
    normalized = st._normalize_balance(balance_rows, total_equity=st._total_equity_from_account(account))
    assert normalized["cash_balance"] == 1234.56
    assert normalized["buying_power"] == 5000.0
    assert normalized["total_equity"] == 25000.0


def test_normalize_position_new_api_shape() -> None:
    """SnapTrade v2 positions use instrument, cost_basis, and string numerics."""
    row = {
        "instrument": {
            "kind": "stock",
            "id": "inst-aapl",
            "symbol": "AAPL",
            "raw_symbol": "AAPL",
        },
        "units": "10",
        "price": "175.50",
        "cost_basis": "150.25",
        "currency": "USD",
    }
    pos = st._normalize_position(row)
    assert pos["symbol"] == "AAPL"
    assert pos["quantity"] == 10.0
    assert pos["average_cost"] == 150.25
    assert pos["current_price"] == 175.50
    assert pos["market_value"] == pytest.approx(1755.0)
    assert pos["unrealized_pnl"] == pytest.approx(252.5)
    assert pos["currency"] == "USD"


def test_normalize_position_legacy_shape() -> None:
    row = {
        "symbol": {"symbol": {"symbol": "MSFT", "raw_symbol": "MSFT"}},
        "units": 5,
        "price": 420.0,
        "average_purchase_price": 380.0,
        "open_pnl": 200.0,
        "currency": {"code": "USD"},
    }
    pos = st._normalize_position(row)
    assert pos["symbol"] == "MSFT"
    assert pos["average_cost"] == 380.0
    assert pos["current_price"] == 420.0
    assert pos["unrealized_pnl"] == 200.0
    assert pos["market_value"] == pytest.approx(2100.0)


def test_normalize_position_does_not_use_price_as_average_cost() -> None:
    row = {
        "instrument": {"kind": "stock", "id": "x", "symbol": "TSLA", "raw_symbol": "TSLA"},
        "units": "2",
        "price": "250.00",
        "currency": "USD",
    }
    pos = st._normalize_position(row)
    assert pos["average_cost"] == 0.0
    assert pos["current_price"] == 250.0


def test_fetch_day_pnl_uses_return_percent() -> None:
    body = {"data": [{"timeframe": "1D", "return_percent": 2.5}]}
    rates = body.get("data")
    row = rates[0]
    pct = row.get("return_percent") or row.get("returnPercent")
    assert pct == 2.5
    assert 10000.0 * (float(pct) / 100.0) == 250.0


@pytest.mark.asyncio
async def test_fetch_balance_uses_account_row_without_extra_list_call() -> None:
    balance_rows = [{"currency": {"code": "USD"}, "cash": 500.0, "buying_power": 2000.0}]
    account = {"id": "acc-1", "balance": {"total": {"amount": 9900.0, "currency": "USD"}}}
    list_mock = AsyncMock()
    with (
        patch.object(st, "_call", AsyncMock(return_value=type("R", (), {"body": balance_rows})())),
        patch.object(st, "list_accounts", list_mock),
    ):
        balance = await st.fetch_balance("user", "secret", "acc-1", account_row=account)
    list_mock.assert_not_called()
    assert balance["total_equity"] == 9900.0


@pytest.mark.asyncio
async def test_fetch_balance_maps_account_total_equity() -> None:
    balance_rows = [{"currency": {"code": "USD"}, "cash": 1000.0, "buying_power": 4000.0}]
    accounts = [{"id": "acc-1", "balance": {"total": {"amount": 18500.75, "currency": "USD"}}}]
    with (
        patch.object(st, "_call", AsyncMock(return_value=type("R", (), {"body": balance_rows})())),
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
    ):
        balance = await st.fetch_balance("user", "secret", "acc-1")
    assert balance["cash_balance"] == 1000.0
    assert balance["buying_power"] == 4000.0
    assert balance["total_equity"] == 18500.75


@pytest.mark.asyncio
async def test_fetch_positions_normalizes_results_payload() -> None:
    payload = {
        "results": [
            {
                "instrument": {
                    "kind": "stock",
                    "id": "inst-nvda",
                    "symbol": "NVDA",
                    "raw_symbol": "NVDA",
                },
                "units": "3",
                "price": "900.00",
                "cost_basis": "800.00",
                "currency": "USD",
            }
        ],
        "data_freshness": {"status": "fresh"},
    }
    with patch.object(st, "_call", AsyncMock(return_value=type("R", (), {"body": payload})())):
        positions = await st.fetch_positions("user", "secret", "acc-1")
    assert len(positions) == 1
    assert positions[0]["symbol"] == "NVDA"
    assert positions[0]["average_cost"] == 800.0
    assert positions[0]["current_price"] == 900.0
    assert positions[0]["market_value"] == pytest.approx(2700.0)
    assert positions[0]["unrealized_pnl"] == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_fetch_day_pnl_from_return_percent() -> None:
    response = type("R", (), {"body": {"data": [{"timeframe": "1D", "return_percent": -1.2}]}})()
    with patch.object(st, "_call", AsyncMock(return_value=response)):
        day_pnl = await st.fetch_day_pnl("user", "secret", "acc-1", 50000.0)
    assert day_pnl == pytest.approx(-600.0)


@pytest.mark.asyncio
async def test_balance_endpoint_caches_accurate_values(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_bal_ok")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-bal-ok", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    accounts = [{"id": "acc-bal-1", "name": "Main", "number": "99998888", "institution_name": "Alpaca"}]
    balance = {"cash_balance": 500.0, "buying_power": 2500.0, "total_equity": 12000.0, "currency": "USD"}
    with (
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
        patch.object(st, "fetch_balance", AsyncMock(return_value={**balance, "as_of_timestamp": datetime.now(timezone.utc).isoformat()})),
        patch.object(st, "fetch_day_pnl", AsyncMock(return_value=45.0)),
        patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-bal-ok", "userSecret": "sec"})),
    ):
        await client.post("/api/brokerage/sync", headers=headers)
        res = await client.get("/api/brokerage/accounts/acc-bal-1/balance", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["cash_balance"] == 500.0
    assert body["buying_power"] == 2500.0
    assert body["total_equity"] == 12000.0
    assert body["day_pnl"] == 45.0


@pytest.mark.asyncio
async def test_positions_endpoint_returns_accurate_fields(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_pos_ok")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-pos-ok", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    accounts = [{"id": "acc-pos-1", "name": "Main", "number": "11112222", "institution_name": "Alpaca"}]
    positions = [
        {
            "symbol": "AAPL",
            "quantity": 10.0,
            "average_cost": 150.25,
            "current_price": 175.50,
            "market_value": 1755.0,
            "unrealized_pnl": 252.5,
            "currency": "USD",
        }
    ]
    with (
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
        patch.object(st, "fetch_balance", AsyncMock(return_value={"cash_balance": 0, "buying_power": 0, "total_equity": 0, "currency": "USD"})),
        patch.object(st, "fetch_day_pnl", AsyncMock(return_value=None)),
        patch.object(st, "fetch_positions", AsyncMock(return_value=positions)),
    ):
        await client.post("/api/brokerage/sync", headers=headers)
        res = await client.get("/api/brokerage/accounts/acc-pos-1/positions", headers=headers)
    assert res.status_code == 200
    row = res.json()["positions"][0]
    assert row["average_cost"] == 150.25
    assert row["current_price"] == 175.50
    assert row["average_cost"] != row["current_price"]
    assert row["market_value"] == 1755.0
    assert row["unrealized_pnl"] == 252.5


@pytest.mark.asyncio
async def test_brokerage_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/brokerage/accounts")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_register_user_idempotent(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_reg")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-1", "userSecret": "sec"})):
        first = await client.post("/api/brokerage/register-user", headers=headers)
        second = await client.post("/api/brokerage/register-user", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["connection_status"] == first.json()["connection_status"]



@pytest.mark.asyncio
async def test_sync_endpoint_populates_accounts(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_sync")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-sync", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    accounts = [
        {
            "id": "acc-sync-1",
            "name": "Sandbox",
            "number": "12345678",
            "institution_name": "Alpaca",
            "raw_type": "INDIVIDUAL",
        }
    ]
    with (
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
        patch.object(
            st,
            "fetch_balance",
            AsyncMock(return_value={"cash_balance": 100.0, "buying_power": 100.0, "total_equity": 500.0, "currency": "USD"}),
        ),
        patch.object(st, "fetch_day_pnl", AsyncMock(return_value=1.5)),
    ):
        sync = await client.post("/api/brokerage/sync", headers=headers)
        listed = await client.get("/api/brokerage/accounts", headers=headers)
    assert sync.status_code == 200
    assert sync.json()["account_count"] == 1
    assert sync.json()["connection_status"] == "connected"
    assert len(listed.json()["accounts"]) == 1
    assert listed.json()["accounts"][0]["broker_name"] == "Alpaca"


@pytest.mark.asyncio
async def test_oauth_callback_invalid_state(client: AsyncClient) -> None:
    res = await client.get("/api/brokerage/callback?state=invalid", follow_redirects=False)
    assert res.status_code == 302
    assert "connected=false" in res.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_missing_state(client: AsyncClient) -> None:
    res = await client.get("/api/brokerage/callback", follow_redirects=False)
    assert res.status_code == 302
    assert "connected=false" in res.headers["location"]


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(client: AsyncClient) -> None:
    res = await client.post("/api/brokerage/webhook", content=b"{}", headers={"Signature": "nope"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_accounts_empty_without_connection(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_empty")
    res = await client.get("/api/brokerage/accounts", headers=headers)
    assert res.status_code == 200
    assert res.json()["accounts"] == []


@pytest.mark.asyncio
async def test_balance_failure_returns_cached_when_available(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_bal_cache")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-bal-cache", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    accounts = [{"id": "acc-cache-1", "name": "Main", "number": "99998888", "institution_name": "Fidelity"}]
    balance_ok = {
        "cash_balance": 2500.0,
        "buying_power": 5000.0,
        "total_equity": 42000.0,
        "currency": "USD",
        "as_of_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with (
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
        patch.object(st, "fetch_balance", AsyncMock(return_value=balance_ok)),
        patch.object(st, "fetch_day_pnl", AsyncMock(return_value=12.5)),
    ):
        await client.post("/api/brokerage/sync", headers=headers)
    with patch.object(st, "fetch_balance", AsyncMock(side_effect=RuntimeError("api down"))):
        res = await client.get("/api/brokerage/accounts/acc-cache-1/balance", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total_equity"] == 42000.0
    assert body["cash_balance"] == 2500.0


@pytest.mark.asyncio
async def test_balance_failure_no_cache_returns_502(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_bal_nocache")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-bal-nc", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    with patch.object(st, "fetch_balance", AsyncMock(side_effect=RuntimeError("api down"))):
        res = await client.get("/api/brokerage/accounts/missing-acc/balance", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_balance_failure_no_placeholder(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_bal")
    with patch.object(st, "register_snaptrade_user", AsyncMock(return_value={"userId": "apex-bal", "userSecret": "sec"})):
        await client.post("/api/brokerage/register-user", headers=headers)
    accounts = [{"id": "acc-1", "name": "Main", "number": "12345678", "institution_name": "Alpaca"}]
    balance_ok = {
        "cash_balance": 100.0,
        "buying_power": 100.0,
        "total_equity": 500.0,
        "currency": "USD",
        "as_of_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with (
        patch.object(st, "list_accounts", AsyncMock(return_value=accounts)),
        patch.object(st, "fetch_balance", AsyncMock(return_value=balance_ok)),
        patch.object(st, "fetch_day_pnl", AsyncMock(return_value=None)),
    ):
        await client.post("/api/brokerage/sync", headers=headers)
    with patch.object(st, "fetch_balance", AsyncMock(side_effect=RuntimeError("api down"))):
        res = await client.get("/api/brokerage/accounts/acc-1/balance", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total_equity"] == 500.0
    assert "Unable to reach" not in str(body)


@pytest.mark.asyncio
async def test_missing_snaptrade_config(client: AsyncClient) -> None:
    headers = await _auth_headers(client, "broker_cfg")
    with patch("app.routers.brokerage.st.get_snaptrade_settings") as mock_settings:
        mock_settings.return_value.configured = False
        res = await client.post("/api/brokerage/register-user", headers=headers)
    assert res.status_code == 503
