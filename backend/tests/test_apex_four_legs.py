"""APEX Strategy is the Full Document §10 four-leg structure, or it is not shown."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.adapters.alpaca import AlpacaAdapter, alpaca_order_error_message
from app.adapters.demo import DemoAdapter
from app.config import Settings
from app.database import Base
from app.models.trading import Position
from app.models.user import User
from app.schemas.market import Quote
from app.services.apex_strategy import ApexStrategyInput
from app.services.fills import execute_strategy_legs
from app.services.stock_leg import build_order_ticket, partition_option_legs
from app.services.strategy_engine import build_strategy_layer, strategy_decision
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.validator import apex_structure_reason, validate_strategy_output

TODAY = date.today()
FRONT = (TODAY + timedelta(days=8)).isoformat()
BACK = (TODAY + timedelta(days=22)).isoformat()
NAME = "APEX Strategy"

CASES = (
    ("bullish", "buy_premium", 0.20),
    ("bearish", "buy_premium", 0.22),
    ("neutral", "fair", 0.25),
    ("neutral", "sell_premium", 0.55),
    ("neutral", "buy_premium", 0.12),
)


def _occ(expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"AAPL{yymmdd}{cp}{int(strike * 1000):08d}"


def _row(strike: float, side: str, expiry: str, bid: float, ask: float, delta: float) -> dict:
    return {
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "symbol": _occ(expiry, side, strike),
        "expiry": expiry,
        "delta": delta,
        "gamma": 0.02,
        "theta": -0.04,
        "vega": 0.11,
    }


def _chains() -> tuple[list[dict], list[dict]]:
    front = [
        _row(105.0, "call", FRONT, 1.20, 1.40, 0.20),
        _row(95.0, "put", FRONT, 1.00, 1.20, -0.20),
        _row(100.0, "call", FRONT, 2.50, 2.70, 0.50),
        _row(100.0, "put", FRONT, 2.30, 2.50, -0.50),
    ]
    back = [
        _row(105.0, "call", BACK, 2.40, 2.60, 0.35),
        _row(95.0, "put", BACK, 2.00, 2.20, -0.32),
    ]
    return front, back


def _metrics(**kwargs):
    front, back = _chains()
    if kwargs.pop("drop_back_put", False):
        back = [row for row in back if row["side"] != "put"]
    return build_registry_metrics(
        "apex_strategy",
        spot=100.0,
        contracts=front,
        back_month_contracts=back,
        front_expiry=FRONT,
        back_expiry=BACK,
        ticker="AAPL",
        **kwargs,
    )


def _eligible() -> ApexStrategyInput:
    return ApexStrategyInput(
        catalyst_days=7,
        term_structure_inverted=True,
        front_iv=0.45,
        back_iv=0.35,
        front_ivr=75.0,
        four_leg_structure=True,
        legs_same_strikes=True,
        call_delta=0.20,
        put_delta=0.20,
        front_premium_offset_pct=0.55,
        adv=6_000_000,
        open_interest=2000,
        spread_pct=5.0,
        earnings_date_confirmed=True,
        earnings_history_hits=6,
        earnings_history_count=8,
        front_expiry_listed=True,
        back_expiry_listed=True,
    )


@pytest.mark.parametrize(("direction", "vol_signal", "iv"), CASES)
def test_apex_recommendation_is_four_legs_or_not_apex(direction: str, vol_signal: str, iv: float) -> None:
    metrics = _metrics(iv=iv)
    assert metrics is not None
    assert apex_structure_reason(metrics["legs"], spot=100.0) is None
    assert len(metrics["legs"]) == 4
    validation = validate_strategy_output(NAME, metrics, "AAPL", spot=100.0)
    assert validation.valid, validation.errors
    decision = strategy_decision(
        composite=88.0,
        direction=direction,
        vol_signal=vol_signal,
        rsi=50.0,
        iv=iv,
        hv=0.25,
        tech_score=70.0,
        catalyst_active=True,
        catalyst_days=7,
        apex_input=_eligible(),
        back_month_available=True,
        symbol="AAPL",
        spot=100.0,
    )
    if decision.best_match == NAME:
        assert len(metrics["legs"]) == 4
    else:
        assert decision.best_match != NAME

    broken = _metrics(iv=iv, drop_back_put=True)
    assert broken is not None
    assert broken["legs"] == []
    assert broken["validation_blocked"] is True
    assert "four legs" in broken["validation_error"].lower()
    blocked = validate_strategy_output(NAME, broken, "AAPL", spot=100.0)
    assert not blocked.valid


def test_failed_apex_gates_do_not_leave_a_partial_name() -> None:
    decision = strategy_decision(
        composite=88.0,
        direction="neutral",
        vol_signal="sell_premium",
        rsi=50.0,
        iv=0.40,
        hv=0.22,
        tech_score=60.0,
        catalyst_active=True,
        catalyst_days=2,
        apex_input=ApexStrategyInput(
            catalyst_days=2,
            term_structure_inverted=False,
            front_ivr=40.0,
            four_leg_structure=False,
            legs_same_strikes=False,
        ),
        back_month_available=True,
        symbol="AAPL",
        spot=100.0,
    )
    assert decision.best_match != NAME
    assert decision.rejection_reasons


def test_combined_max_loss_is_the_net_debit() -> None:
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    legs = metrics["legs"]
    multiplier = metrics["per_contract_multiplier"]
    long_cost = sum(leg["mid"] for leg in legs if leg["action"] == "buy")
    front_premium = sum(leg["mid"] for leg in legs if leg["action"] == "sell")
    net = long_cost - front_premium
    assert net > 0
    assert metrics["net_type"] == "debit"
    assert metrics["max_loss"] == round(net * multiplier, 2)
    assert metrics["max_loss"] > 0
    assert metrics["capital_required"] == metrics["max_loss"]
    assert metrics["max_loss_basis"] == "net_debit"
    assert isinstance(metrics["max_profit"], (int, float))
    assert metrics["max_profit_unlimited_allowed"] is not True
    assert metrics["greeks"]["delta"] is not None
    assert len(metrics["payoff_grid"]) >= 5
    layer = build_strategy_layer(
        strategy_name=NAME,
        composite=88.0,
        direction="neutral",
        vol_signal="sell_premium",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 100.0,
            "expiry": FRONT,
            "contracts": _chains()[0],
            "recommendedContract": {"strike": 105.0, "side": "call", "expiry": FRONT},
        },
        vol_layer={"iv_rank": 75, "iv": 0.40},
        sentiment_layer={},
        fundamentals_layer={"score": 60},
        tech_score=70.0,
        back_month_contracts=_chains()[1],
        back_expiry=BACK,
        ticker="AAPL",
    )
    # The fixture quotes are about 15% and 18% of mid, wider than the 8% cap on all four legs.
    assert layer["tradeable"] is False
    assert layer["execution_banner"] == "NOT EXECUTABLE"
    text = f"{layer['what_is_this']} {layer['how_to_execute']}"
    for leg in layer["metrics"]["legs"]:
        assert str(leg["strike"]) in text or f"{leg['strike']:g}" in text
        assert str(leg["expiry"]) in text
        assert f"{leg['mid']:.2f}" in text
    ticket, equity = build_order_ticket(
        layer["metrics"],
        tradeable=True,
        equity_required=False,
        ticker="AAPL",
    )
    assert equity == []
    assert [row["symbol"] for row in ticket] == [leg["symbol"] for leg in layer["metrics"]["legs"]]
    assert all(row["price"] == leg["mid"] for row, leg in zip(ticket, layer["metrics"]["legs"], strict=True))
    certificate_legs = layer["metrics"]["legs"]
    assert [leg["symbol"] for leg in certificate_legs] == [row["symbol"] for row in ticket]


class _SeqAdapter:
    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.symbols: list[str] = []
        self.payloads: list[dict] = []

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol,
            name=symbol,
            price=2.0,
            source="test",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    async def submit_order(self, **kwargs) -> dict:
        self.symbols.append(str(kwargs["symbol"]))
        self.payloads.append(dict(kwargs))
        if self.fail == "COMBO" or (self.fail and kwargs.get("symbol") == self.fail):
            return {"status": "rejected", "rejected": True, "reason": "Broker rejected the order"}
        return {"status": "filled", "filled_avg_price": kwargs.get("limit_price") or 2.0}


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


def _order_legs() -> list[dict]:
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    return [
        {
            "symbol": leg["symbol"],
            "side": leg["action"],
            "option_side": leg["side"],
        }
        for leg in reversed(metrics["legs"])
    ]


@pytest.mark.asyncio
async def test_four_legs_buy_before_short(db: AsyncSession) -> None:
    adapter = _SeqAdapter()
    user = _user()
    db.add(user)
    await db.commit()
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    ticket = _priced_legs()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=ticket,
        contracts_per_leg=1,
    )
    assert len(orders) == 1
    assert orders[0].order_type == "limit"
    assert len(adapter.symbols) == 1
    assert adapter.symbols[0] not in {leg["symbol"] for leg in ticket}
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert {row.symbol for row in held} == {leg["symbol"] for leg in metrics["legs"]}


@pytest.mark.asyncio
async def test_rejected_long_does_not_send_shorts(db: AsyncSession) -> None:
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    legs = _priced_legs()
    shorts = [leg["symbol"] for leg in legs if leg["side"] == "sell"]
    adapter = _SeqAdapter(fail="COMBO")
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="not split into market orders") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=legs,
            contracts_per_leg=1,
        )
    assert "No short leg was submitted" in str(raised.value)
    assert len(adapter.symbols) == 1
    for symbol in shorts:
        assert symbol not in adapter.symbols
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert held == []


@pytest.mark.asyncio
async def test_rejected_short_does_not_send_the_other_short(db: AsyncSession) -> None:
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    legs = _priced_legs()
    adapter = _SeqAdapter(fail="COMBO")
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="not split into market orders") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=legs,
            contracts_per_leg=1,
        )
    assert "No short leg was submitted" in str(raised.value)
    assert len(adapter.payloads) == 1
    assert adapter.payloads[0]["order_class"] == "mleg"
    assert adapter.payloads[0]["order_type"] == "limit"
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert held == []
    assert metrics["legs"]


def _priced_legs() -> list[dict]:
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    return [
        {
            "symbol": leg["symbol"],
            "side": leg["action"],
            "option_side": leg["side"],
            "price": leg["mid"],
        }
        for leg in reversed(metrics["legs"])
    ]


class _InflatedQuote:
    """Stock-style quote of an OCC symbol. The chain mid is the price the card showed."""

    def __init__(self) -> None:
        self.symbols: list[str] = []

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol,
            name=symbol,
            price=100.0,
            source="test",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    async def submit_order(self, **kwargs) -> dict:
        self.symbols.append(str(kwargs["symbol"]))
        return {"status": "filled"}


class _MarketHours:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol,
            name=symbol,
            price=2.0,
            source="test",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    async def submit_order(self, **kwargs) -> dict:
        self.symbols.append(str(kwargs["symbol"]))
        return {
            "status": "rejected",
            "rejected": True,
            "reason": "options market orders are only allowed during market hours",
        }


@pytest.mark.asyncio
async def test_apex_fills_at_chain_mids_when_the_occ_quote_is_a_stock_price(db: AsyncSession) -> None:
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    adapter = _InflatedQuote()
    user = _user()
    user.cash_balance = 5_000.0
    user.buying_power = 5_000.0
    user.portfolio_value = 5_000.0
    db.add(user)
    await db.commit()
    legs = _priced_legs()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=legs,
        contracts_per_leg=1,
    )
    net = sum(leg["price"] if leg["side"] == "buy" else -leg["price"] for leg in legs)
    assert len(orders) == 1
    assert orders[0].order_type == "limit"
    assert orders[0].fill_price == pytest.approx(abs(net))
    assert len(adapter.symbols) == 1
    assert user.buying_power > 4_000


@pytest.mark.asyncio
async def test_apex_four_legs_fill_on_the_demo_adapter(db: AsyncSession) -> None:
    metrics = _metrics(iv=0.40)
    assert metrics is not None
    user = _user()
    user.cash_balance = 5_000.0
    user.buying_power = 5_000.0
    user.portfolio_value = 5_000.0
    db.add(user)
    await db.commit()
    legs = _priced_legs()
    buys, shorts = partition_option_legs(legs)
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=DemoAdapter(),
        legs=legs,
        contracts_per_leg=1,
    )
    net = sum(leg["price"] if leg["side"] == "buy" else -leg["price"] for leg in legs)
    assert len(orders) == 1
    assert orders[0].status == "filled"
    assert orders[0].order_type == "limit"
    assert orders[0].fill_price == pytest.approx(abs(net))
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    qty_by_symbol = {row.symbol: row.qty for row in held}
    for leg in buys:
        assert qty_by_symbol[leg["symbol"]] == 1
    for leg in shorts:
        assert qty_by_symbol[leg["symbol"]] == -1


@pytest.mark.asyncio
async def test_market_hours_rejection_paper_fills_apex_and_holds_the_shorts(db: AsyncSession) -> None:
    legs = _priced_legs()
    buys, shorts = partition_option_legs(legs)
    adapter = _MarketHours()
    user = _user()
    db.add(user)
    await db.commit()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=legs,
        contracts_per_leg=1,
    )
    net = sum(leg["price"] if leg["side"] == "buy" else -leg["price"] for leg in legs)
    assert len(orders) == 1
    assert orders[0].status == "filled"
    assert orders[0].order_type == "limit"
    assert orders[0].fill_price == pytest.approx(abs(net))
    assert len(adapter.symbols) == 1
    for leg in shorts:
        assert leg["symbol"] not in adapter.symbols
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    qty_by_symbol = {row.symbol: row.qty for row in held}
    for leg in buys:
        assert qty_by_symbol[leg["symbol"]] == 1
    for leg in shorts:
        assert qty_by_symbol[leg["symbol"]] == -1


@pytest.mark.asyncio
async def test_real_brokerage_keeps_the_market_hours_reason(db: AsyncSession) -> None:
    legs = _priced_legs()
    _, shorts = partition_option_legs(legs)
    adapter = _MarketHours()
    user = _user()
    user.account_mode = "real_brokerage"
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="options market orders are only allowed during market hours") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=legs,
            contracts_per_leg=1,
        )
    assert str(raised.value).startswith("options market orders are only allowed during market hours")
    assert "not split into market orders" in str(raised.value)
    assert "No short leg was submitted" in str(raised.value)
    for leg in shorts:
        assert leg["symbol"] not in adapter.symbols
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert held == []


def test_alpaca_order_error_message_is_the_broker_sentence() -> None:
    body = {"code": 42210000, "message": "options market orders are only allowed during market hours"}
    assert (
        alpaca_order_error_message(body, fallback="Broker rejected the order")
        == "options market orders are only allowed during market hours"
    )


@pytest.mark.asyncio
async def test_alpaca_strict_rejection_returns_the_market_hours_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _Resp:
        status_code = 422
        text = '{"message":"options market orders are only allowed during market hours"}'

        def json(self) -> dict:
            return {"code": 42210000, "message": "options market orders are only allowed during market hours"}

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: object) -> bool:
            del args
            return False

        async def post(self, url: str, headers: dict | None = None, json: dict | None = None) -> _Resp:
            del url, headers
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr("app.adapters.alpaca.httpx.AsyncClient", _Client)
    adapter = AlpacaAdapter(Settings(alpaca_api_key_id="test-key", alpaca_api_secret_key="test-secret"))
    result = await adapter.submit_order(
        symbol="DAL261009C00084000",
        qty=1.0,
        side="buy",
        order_type="market",
        strict=True,
    )
    assert result["rejected"] is True
    assert result["reason"] == "options market orders are only allowed during market hours"
    assert captured["json"]["qty"] == 1
