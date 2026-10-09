from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.trading import Order, Position
from app.models.user import User
from app.services.portfolio_pnl import pnl_history_points, replay_filled_orders, symbol_pnl_rows


def _order(
    symbol: str,
    side: str,
    qty: float,
    fill_price: float,
    *,
    asset_class: str = "us_equity",
    status: str = "filled",
) -> Order:
    o = Order(
        user_id="u1",
        symbol=symbol,
        side=side,
        qty=qty,
        order_type="market",
        fill_price=fill_price,
        status=status,
        asset_class=asset_class,
        multiplier=100 if asset_class == "us_option" else 1,
    )
    return o


def test_replay_realized_on_round_trip() -> None:
    orders = [
        _order("AAPL", "buy", 10, 100.0),
        _order("AAPL", "sell", 10, 110.0),
    ]
    books = replay_filled_orders(orders)
    assert books["AAPL"].realized_pl == pytest.approx(100.0)
    assert books["AAPL"].qty == 0


def test_option_realized_uses_multiplier() -> None:
    orders = [
        _order("AAPL240119C00150000", "buy", 2, 4.0, asset_class="us_option"),
        _order("AAPL240119C00150000", "sell", 2, 5.0, asset_class="us_option"),
    ]
    books = replay_filled_orders(orders)
    assert books["AAPL240119C00150000"].realized_pl == pytest.approx(200.0)


def test_symbol_pnl_open_and_closed() -> None:
    orders = [
        _order("AAPL", "buy", 10, 100.0),
        _order("MSFT", "buy", 5, 200.0),
        _order("MSFT", "sell", 5, 220.0),
    ]
    positions = [
        Position(user_id="u1", symbol="AAPL", qty=10, avg_cost=100.0, current_price=105.0, asset_class="us_equity"),
    ]
    rows = {r.symbol: r for r in symbol_pnl_rows(orders, positions)}
    assert rows["AAPL"].is_open is True
    assert rows["AAPL"].unrealized_pl == pytest.approx(50.0)
    assert rows["MSFT"].is_open is False
    assert rows["MSFT"].realized_pl == pytest.approx(100.0)


def test_pnl_history_omits_days_without_observations() -> None:
    created = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
    user = User(
        id="u1",
        username="flat",
        email="flat@example.com",
        password_hash="x",
        cash_balance=100_000,
        starting_balance=100_000,
        account_mode="paper_funded",
        created_at=created,
    )
    points = pnl_history_points(user, [], [])
    assert len(points) == 2
    assert points[0]["t"].startswith("2026-08-01")
    assert points[0]["portfolio_value"] == 100_000
    assert points[0]["balance"] == 100_000
    assert points[0]["cumulative_pl"] == 0
    live = datetime.fromisoformat(points[1]["t"])
    assert live.date() == datetime.now(timezone.utc).date()
    assert points[1]["portfolio_value"] == 100_000
    assert points[1]["cumulative_pl"] == 0


def test_pnl_history_is_open_fill_and_live_mark() -> None:
    created = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
    filled = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
    user = User(
        id="u1",
        username="marks",
        email="marks@example.com",
        password_hash="x",
        cash_balance=99_000,
        starting_balance=100_000,
        account_mode="paper_funded",
        created_at=created,
    )
    order = _order("AAPL", "buy", 10, 100.0)
    order.filled_at = filled
    position = Position(
        user_id="u1",
        symbol="AAPL",
        qty=10,
        avg_cost=100.0,
        current_price=110.0,
        asset_class="us_equity",
    )
    points = pnl_history_points(user, [order], [position])
    assert [p["t"][:10] for p in points] == ["2026-08-01", "2026-08-20", points[-1]["t"][:10]]
    assert len(points) == 3
    # Open: starting cash, no positions.
    assert points[0]["portfolio_value"] == 100_000
    # Fill: cash 99,000 after spending 1,000, marked at the 100 fill → 100,000.
    assert points[1]["portfolio_value"] == 100_000
    # Live: cash_balance 99,000 + 10 × 110 = 100,100.
    assert points[2]["portfolio_value"] == 100_100


def test_short_option_unrealized_gains_when_mark_falls() -> None:
    positions = [
        Position(
            user_id="u1",
            symbol="AAPL270115P00150000",
            qty=-1,
            avg_cost=4.0,
            current_price=3.0,
            asset_class="us_option",
        )
    ]
    rows = symbol_pnl_rows([], positions)
    # (3 − 4) × (−1) × 100 = +100
    assert rows[0].unrealized_pl == 100.0
    assert rows[0].total_pl == 100.0
    assert rows[0].is_open is True
    assert rows[0].qty == -1


def test_pnl_history_naive_db_timestamps() -> None:
    """SQLite stores naive datetimes; pnl history must not 500 when comparing to UTC."""
    created = datetime(2026, 8, 24, 4, 55, 56)  # naive, like apex.db rows
    user = User(
        id="u1",
        username="naive",
        email="naive@example.com",
        password_hash="x",
        cash_balance=90_000,
        starting_balance=100_000,
        account_mode="paper_funded",
        created_at=created,
    )
    order = _order("AAPL", "buy", 10, 100.0)
    order.filled_at = datetime(2026, 8, 24, 5, 1, 17)  # naive fill time
    position = Position(
        user_id="u1",
        symbol="AAPL",
        qty=10,
        avg_cost=100.0,
        current_price=105.0,
        asset_class="us_equity",
    )
    points = pnl_history_points(user, [order], [position])
    assert len(points) >= 1
    assert points[-1]["portfolio_value"] > 0


@pytest.mark.asyncio
async def test_portfolio_endpoints_and_close(client: AsyncClient) -> None:
    signup = await client.post(
        "/auth/signup",
        json={
            "full_name": "Port User",
            "username": "portuser",
            "email": "port@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 50000,
        },
    )
    assert signup.status_code == 201

    login = await client.post("/auth/login", json={"username": "portuser", "password": "ApexDesk!23"})
    otp = await client.post("/auth/otp/request", json={"username": "portuser"})
    code = otp.json()["code"]
    tok = await client.post("/auth/otp/verify", json={"username": "portuser", "code": code})
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}

    hist = await client.get("/api/portfolio/pnl-history", headers=headers)
    assert hist.status_code == 200
    body = hist.json()
    assert body["starting_balance"] == 50000
    assert len(body["points"]) >= 1
    assert body["points"][0]["portfolio_value"] == 50000
    assert body["points"][0]["cumulative_pl"] == 0

    occ = "AAPL270115C00150000"
    buy = await client.post(
        "/api/orders",
        json={
            "thesis_accepted": True,
            "asset_class": "us_option",
            "legs": [{"symbol": occ, "side": "buy", "qty": 1}],
            "contracts_per_leg": 1,
        },
        headers=headers,
    )
    if buy.status_code != 200:
        # A dark live quote is not filled from a demo price, and no position is invented.
        assert buy.status_code in {400, 503}
        held = await client.get("/api/positions", headers=headers)
        assert held.status_code == 200
        assert held.json()["positions"] == []
        return

    pos = await client.get("/api/positions", headers=headers)
    position_id = pos.json()["positions"][0]["id"]
    position_symbol = pos.json()["positions"][0]["symbol"]

    orders = await client.get("/api/orders", headers=headers)
    assert orders.status_code == 200
    assert len(orders.json()["orders"]) >= 1

    overall = await client.get("/api/portfolio/overall-pnl", headers=headers)
    assert overall.status_code == 200
    assert any(r["symbol"] == position_symbol for r in overall.json()["rows"])

    close = await client.post(f"/api/positions/{position_id}/close", headers=headers)
    assert close.status_code == 200
    assert close.json()["ok"] is True

    after = await client.get("/api/positions", headers=headers)
    assert after.json()["positions"] == []
