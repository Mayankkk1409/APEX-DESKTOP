"""Covered-call stock legs follow holdings and the chain multiplier."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.adapters.demo import DemoAdapter
from app.database import Base
from app.models.trading import Position
from app.models.user import User
from app.schemas.market import Quote
from app.services.fills import execute_strategy_legs
from app.services.stock_leg import Holdings, plan_stock, read_holdings
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.payoffs.core import covered_call_payoff, protective_put_payoff

ROOT = Path(__file__).resolve().parents[2]
TODAY = date.today()
FRONT = (TODAY + timedelta(days=30)).isoformat()
FORBIDDEN = "options overlay only; stock is not submitted"
ASSUMPTION = "Assumes you already hold 100 shares per contract"


def _occ(side: str, strike: float) -> str:
    yymmdd = FRONT.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"AAPL{yymmdd}{cp}{int(strike * 1000):08d}"


def _chain(*, multiplier: int | None = None) -> list[dict]:
    rows = []
    for strike, side, delta, bid, ask in (
        (95.0, "put", -0.40, 3.0, 3.2),
        (100.0, "call", 0.55, 4.0, 4.2),
        (100.0, "put", -0.45, 3.4, 3.6),
        (105.0, "call", 0.30, 2.0, 2.2),
        (110.0, "call", 0.15, 1.0, 1.2),
    ):
        row = {
            "side": side,
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "symbol": _occ(side, strike),
            "expiry": FRONT,
            "delta": delta,
        }
        if multiplier is not None:
            row["multiplier"] = multiplier
        rows.append(row)
    return rows


def _covered(**kwargs):
    metrics = build_registry_metrics(
        "covered_call",
        spot=100.0,
        contracts=_chain(multiplier=kwargs.pop("multiplier", None)),
        front_expiry=FRONT,
        ticker="AAPL",
        contract_multiplier=kwargs.pop("contract_multiplier", 100),
        **kwargs,
    )
    assert metrics is not None
    return metrics


def _stock(metrics: dict) -> dict:
    return next(leg for leg in metrics["legs"] if leg.get("side") == "stock")


def test_covered_call_with_zero_shares_buys_the_chain_multiplier() -> None:
    metrics = _covered(shares_held=0, stock_ask=101.25)
    stock = _stock(metrics)
    assert stock["order_qty"] == 100
    assert stock["action"] == "buy"
    assert "Buying 100 shares" in metrics["equity_note"]
    call = next(leg for leg in metrics["legs"] if leg.get("side") == "call")
    expected = covered_call_payoff(
        stock_cost=101.25,
        call_strike=call["strike"],
        call_premium=call["mid"],
        shares=100,
    )
    assert metrics["max_profit"] == expected["max_profit"]
    assert metrics["max_loss"] == expected["max_loss"]
    assert metrics["breakevens"] == expected["breakevens"]
    assert metrics["stock_entry_source"] == "live ask"


def test_covered_call_with_enough_unencumbered_shares_does_not_buy() -> None:
    metrics = _covered(shares_held=100, share_avg_cost=42.5, stock_ask=101.25)
    stock = _stock(metrics)
    assert stock["order_qty"] == 0
    assert stock["already_held"] is True
    assert "Using 100 shares already held" in metrics["equity_note"]
    assert "$42.50" in metrics["equity_note"]
    assert "No additional shares are bought" in metrics["equity_note"]
    call = next(leg for leg in metrics["legs"] if leg.get("side") == "call")
    expected = covered_call_payoff(
        stock_cost=42.5,
        call_strike=call["strike"],
        call_premium=call["mid"],
        shares=100,
    )
    assert metrics["max_profit"] == expected["max_profit"]
    assert metrics["stock_entry"] == 42.5


def test_covered_call_partial_holdings_buy_only_the_shortfall() -> None:
    metrics = _covered(shares_held=40, share_avg_cost=10, stock_ask=11)
    stock = _stock(metrics)
    assert stock["order_qty"] == 60
    assert stock["shares_used"] == 40
    assert "Buying 60 shares" in metrics["equity_note"]
    assert metrics["stock_entry"] == 10.6


def test_shares_covering_another_short_call_are_not_reused() -> None:
    metrics = _covered(shares_held=100, shares_encumbered=100, stock_ask=50)
    assert _stock(metrics)["order_qty"] == 100
    assert "already cover another short call" in metrics["equity_note"]


def test_chain_multiplier_sets_share_quantity() -> None:
    metrics = _covered(multiplier=10, contract_multiplier=100, shares_held=0, stock_ask=50)
    assert metrics["per_contract_multiplier"] == 10
    assert _stock(metrics)["order_qty"] == 10


def test_covered_call_and_protective_put_use_cents() -> None:
    covered = covered_call_payoff(stock_cost="100.10", call_strike="105", call_premium="1.25", shares=100)
    assert covered["max_profit"] == 615.0
    assert covered["max_loss"] == 9885.0
    assert covered["breakevens"] == [98.85]
    protective = protective_put_payoff(stock_cost="100.10", put_strike="95.50", put_premium="2.05", shares=100)
    assert protective["max_loss"] == 665.0
    assert protective["breakevens"] == [102.15]
    assert protective["max_profit"] is None
    assert protective["max_profit_unlimited_allowed"] is True


def test_short_stock_is_infeasible_without_a_locate() -> None:
    metrics = build_registry_metrics(
        "covered_put",
        spot=100.0,
        contracts=_chain(),
        front_expiry=FRONT,
        ticker="AAPL",
    )
    assert metrics is not None
    assert metrics["validation_blocked"] is True
    assert metrics["validation_error"] == "cannot confirm easy-to-borrow / margin"
    assert metrics["equity_note"] == "cannot confirm easy-to-borrow / margin"
    stock = _stock(metrics)
    assert stock["side"] == "stock"
    assert stock["action"] == "sell"
    assert stock["order_qty"] == 0
    assert stock["short_unconfirmed"] is True
    assert "shortable" not in metrics["equity_note"].lower()


def test_forbidden_overlay_sentence_is_absent() -> None:
    paths = [
        ROOT / "frontend/src/components/StrategyScan.tsx",
        ROOT / "frontend/src/pages/DeepScan.tsx",
        ROOT / "backend/app/services/scan_engine.py",
        ROOT / "backend/app/services/strategy_engine.py",
        ROOT / "backend/app/services/stock_leg.py",
    ]
    for path in paths:
        text = path.read_text()
        assert FORBIDDEN not in text
        assert ASSUMPTION not in text


def test_read_holdings_subtracts_shares_covering_a_short_call() -> None:
    positions = [
        SimpleNamespace(symbol="AAPL", asset_class="us_equity", qty=150, avg_cost=42.5, multiplier=1),
        SimpleNamespace(symbol=_occ("call", 105), asset_class="us_option", qty=-1, avg_cost=2, multiplier=100),
    ]
    held = read_holdings(positions, "AAPL")
    assert held.shares_long == 150
    assert held.shares_encumbered == 100
    assert held.unencumbered_long == 50
    plan = plan_stock(
        equity_side="buy",
        contracts=1,
        multiplier=100,
        holdings=held,
        ask=50,
    )
    assert plan.order_qty == 50
    assert plan.shares_used == 50


class _SeqAdapter:
    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.symbols: list[str] = []

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, name=symbol, price=10.0, source="test")

    async def submit_order(self, **kwargs) -> dict:
        self.symbols.append(str(kwargs["symbol"]))
        if kwargs.get("order_class") == "mleg" and self.fail == "COMBO":
            return {"status": "rejected", "rejected": True, "reason": "multi-leg orders are not supported"}
        if self.fail and kwargs["symbol"] == self.fail:
            return {"status": "rejected", "rejected": True}
        return {"status": "filled", "filled_avg_price": 10.0}


def _user() -> User:
    uid = str(uuid4())
    return User(
        id=uid,
        full_name="Trader",
        username=f"u{uid[:8]}",
        email=f"{uid[:8]}@example.com",
        password_hash="x",
        account_mode="paper_funded",
        cash_balance=100_000.0,
        buying_power=100_000.0,
        portfolio_value=100_000.0,
        starting_balance=100_000.0,
    )


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_stock_fills_before_the_short_call(db: AsyncSession) -> None:
    adapter = _SeqAdapter()
    user = _user()
    db.add(user)
    await db.commit()
    put = _occ("put", 95)
    call = _occ("call", 105)
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=[
            {"symbol": call, "side": "sell", "option_side": "call"},
            {"symbol": put, "side": "buy", "option_side": "put"},
        ],
        equity_legs=[{"symbol": "AAPL", "side": "buy", "qty": 100}],
        contracts_per_leg=1,
    )
    assert adapter.symbols[0] == "AAPL"
    assert len(orders) == 2
    assert orders[0].symbol == "AAPL"
    assert orders[0].asset_class == "us_equity"
    assert orders[0].status == "filled"
    assert orders[1].order_type == "limit"
    assert orders[1].asset_class == "us_option"
    held_call = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == call))
    held_put = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == put))
    assert held_call is not None and held_call.qty == -1
    assert held_put is not None and held_put.qty == 1


@pytest.mark.asyncio
async def test_failed_option_does_not_submit_the_short_call(db: AsyncSession) -> None:
    put = _occ("put", 95)
    call = _occ("call", 105)
    adapter = _SeqAdapter(fail="COMBO")
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="not split into market orders") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=[
                {"symbol": put, "side": "buy", "option_side": "put", "price": 1.0},
                {"symbol": call, "side": "sell", "option_side": "call", "price": 1.2},
            ],
            equity_legs=[{"symbol": "AAPL", "side": "buy", "qty": 100}],
            contracts_per_leg=1,
        )
    assert "No short leg was submitted" in str(raised.value)
    assert call not in adapter.symbols
    assert put not in adapter.symbols
    assert adapter.symbols[0] == "AAPL"
    held_call = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == call))
    assert held_call is None


@pytest.mark.asyncio
async def test_unconfirmed_short_stock_is_not_submitted(db: AsyncSession) -> None:
    adapter = _SeqAdapter()
    user = _user()
    db.add(user)
    await db.commit()
    put = _occ("put", 95)
    with pytest.raises(ValueError, match="cannot confirm easy-to-borrow / margin"):
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=[{"symbol": put, "side": "sell", "option_side": "put"}],
            equity_legs=[{"symbol": "AAPL", "side": "sell", "qty": 100}],
            contracts_per_leg=1,
        )
    assert adapter.symbols == []


@pytest.mark.asyncio
async def test_insufficient_buying_power_names_the_reason(db: AsyncSession) -> None:
    call = _occ("call", 105)
    adapter = _SeqAdapter()
    user = _user()
    user.cash_balance = 500.0
    user.buying_power = 500.0
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="Insufficient buying power") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=[{"symbol": call, "side": "sell", "option_side": "call", "price": 1.25}],
            equity_legs=[{"symbol": "AAPL", "side": "buy", "qty": 100}],
            contracts_per_leg=1,
        )
    assert "The short call was not submitted" in str(raised.value)
    assert adapter.symbols == []


@pytest.mark.asyncio
async def test_covered_call_fills_stock_then_call_on_the_demo_adapter(db: AsyncSession) -> None:
    adapter = DemoAdapter()
    user = _user()
    db.add(user)
    await db.commit()
    call = _occ("call", 105)
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=[{"symbol": call, "side": "sell", "option_side": "call", "price": 1.30}],
        equity_legs=[{"symbol": "AAPL", "side": "buy", "qty": 100}],
        contracts_per_leg=1,
    )
    assert [order.symbol for order in orders] == ["AAPL", call]
    assert all(order.status == "filled" for order in orders)
    assert orders[0].asset_class == "us_equity"
    assert orders[0].qty == 100
    assert orders[1].fill_price == 1.30
    short = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == call))
    assert short is not None
    assert short.qty == -1


class _ClosedAdapter:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, name=symbol, price=50.0, source="test")

    async def submit_order(self, **kwargs) -> dict:
        self.symbols.append(str(kwargs["symbol"]))
        return {"status": "rejected", "rejected": True, "reason": "market is closed"}


@pytest.mark.asyncio
async def test_closed_market_paper_fills_the_covered_call(db: AsyncSession) -> None:
    call = _occ("call", 105)
    adapter = _ClosedAdapter()
    user = _user()
    db.add(user)
    await db.commit()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=[{"symbol": call, "side": "sell", "option_side": "call", "price": 1.30}],
        equity_legs=[{"symbol": "AAPL", "side": "buy", "qty": 100}],
        contracts_per_leg=1,
    )
    assert [order.symbol for order in orders] == ["AAPL", call]
    assert all(order.status == "filled" for order in orders)
    assert adapter.symbols == ["AAPL"]
    assert call not in adapter.symbols
