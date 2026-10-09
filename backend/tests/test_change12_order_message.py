"""Change 12 agent 4B. A defined-risk spread is one combo. Paper fills the whole structure."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.analysis.gate_config import QUOTE_FRESHNESS_SECONDS
from app.database import Base
from app.models.trading import Position
from app.models.user import User
from app.schemas.market import Quote
from app.services.executability import quote_problem
from app.services.fills import execute_strategy_legs, paper_fill_sentence

_NOW = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
_LONG = "AAPL261218C00100000"
_SHORT = "AAPL261218C00105000"
_UNCOVERED = "Account not eligible to trade uncovered option contracts"
_CLOSED = "market is closed"


def _legs() -> list[dict]:
    return [
        {"symbol": _LONG, "side": "buy", "option_side": "call", "price": 2.50},
        {"symbol": _SHORT, "side": "sell", "option_side": "call", "price": 1.10},
    ]


def _user(mode: str = "paper_funded") -> User:
    uid = str(uuid4())
    return User(
        id=uid,
        full_name="Trader",
        username=f"u{uid[:8]}",
        email=f"{uid[:8]}@example.com",
        password_hash="x",
        account_mode=mode,
        cash_balance=100_000.0,
        buying_power=100_000.0,
        portfolio_value=100_000.0,
        starting_balance=100_000.0,
    )


def _quote(symbol: str, *, as_of: str | None, bid: float = 2.40, ask: float = 2.60) -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
        price=(bid + ask) / 2.0,
        bid=bid,
        ask=ask,
        source="test",
        as_of=as_of,
        asset_class="us_option",
    )


def _fresh_stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Broker:
    def __init__(self, reason: str, *, fresh_reads: int = 10**6, wide_after: int | None = None) -> None:
        self.reason = reason
        self.fresh_reads = fresh_reads
        self.wide_after = wide_after
        self.reads = 0
        self.payloads: list[dict] = []

    async def quote(self, symbol: str) -> Quote:
        self.reads += 1
        as_of = _fresh_stamp() if self.reads <= self.fresh_reads else None
        if self.wide_after is not None and self.reads > self.wide_after:
            return _quote(symbol, as_of=_fresh_stamp(), bid=1.0, ask=2.0)
        return _quote(symbol, as_of=as_of)

    async def submit_order(self, **kwargs: object) -> dict:
        self.payloads.append(dict(kwargs))
        return {"status": "rejected", "rejected": True, "reason": self.reason}


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_quote_cap_and_missing_timestamp_stay_strict() -> None:
    assert QUOTE_FRESHNESS_SECONDS == 300
    fresh = (_NOW - timedelta(seconds=300)).isoformat()
    stale = (_NOW - timedelta(seconds=301)).isoformat()
    assert quote_problem(_quote("AAPL", as_of=fresh), now=_NOW) is None
    problem = quote_problem(_quote("AAPL", as_of=stale), now=_NOW)
    assert problem is not None
    assert "Quote not current" in problem
    assert quote_problem(_quote("AAPL", as_of=None), now=_NOW) == "Quote not current. Quoted unknown time."


@pytest.mark.asyncio
async def test_paper_uncovered_refusal_fills_the_combo_at_the_mid(db: AsyncSession) -> None:
    adapter = _Broker(_UNCOVERED)
    user = _user()
    db.add(user)
    await db.commit()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=_legs(),
        contracts_per_leg=1,
    )
    assert len(orders) == 1
    assert orders[0].status == "filled"
    assert orders[0].order_type == "limit"
    assert orders[0].fill_price == pytest.approx(1.40)
    assert orders[0].fill_note == paper_fill_sentence(_UNCOVERED)
    assert orders[0].fill_note == (
        "Account not eligible to trade uncovered option contracts. The paper order filled at the mid."
    )
    assert "The short call was not submitted" not in orders[0].fill_note
    assert len(adapter.payloads) == 1
    payload = adapter.payloads[0]
    assert payload["order_class"] == "mleg"
    assert payload["order_type"] == "limit"
    assert payload["limit_price"] == pytest.approx(1.40)
    assert [leg["symbol"] for leg in payload["legs"]] == [_LONG, _SHORT]
    assert _SHORT not in {row["symbol"] for row in adapter.payloads}
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    qty = {row.symbol: row.qty for row in held}
    assert qty[_LONG] == 1
    assert qty[_SHORT] == -1


@pytest.mark.asyncio
async def test_paper_closed_market_uses_the_same_sentence(db: AsyncSession) -> None:
    adapter = _Broker(_CLOSED)
    user = _user()
    db.add(user)
    await db.commit()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=_legs(),
        contracts_per_leg=1,
    )
    assert orders[0].fill_note == "market is closed. The paper order filled at the mid."
    assert orders[0].fill_price == pytest.approx(1.40)
    assert len(adapter.payloads) == 1


@pytest.mark.asyncio
async def test_real_brokerage_is_not_paper_filled(db: AsyncSession) -> None:
    adapter = _Broker(_UNCOVERED)
    user = _user("real_brokerage")
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="not eligible to trade uncovered") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=_legs(),
            contracts_per_leg=1,
        )
    text = str(raised.value)
    assert text.startswith(_UNCOVERED)
    assert "The combo was not split into market orders" in text
    assert "No short leg was submitted" in text
    assert "The short call was not submitted" not in text
    assert "The paper order filled" not in text
    assert len(adapter.payloads) == 1
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert held == []


@pytest.mark.asyncio
async def test_other_combo_rejections_do_not_paper_fill_or_stack_the_short(db: AsyncSession) -> None:
    adapter = _Broker("multi-leg orders are not supported")
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="not split into market orders") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=_legs(),
            contracts_per_leg=1,
        )
    text = str(raised.value)
    assert "The short call was not submitted" not in text
    assert "The paper order filled" not in text
    assert len(adapter.payloads) == 1
    assert _SHORT not in {str(row.get("symbol")) for row in adapter.payloads}
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert held == []


@pytest.mark.asyncio
async def test_paper_fill_stops_when_the_recheck_has_no_timestamp(db: AsyncSession) -> None:
    adapter = _Broker(_UNCOVERED, fresh_reads=2)
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="Quoted unknown time") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=_legs(),
            contracts_per_leg=1,
        )
    text = str(raised.value)
    assert "The paper order filled" not in text
    assert "The short call was not submitted" not in text
    assert len(adapter.payloads) == 1
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert held == []


@pytest.mark.asyncio
async def test_paper_fill_stops_when_the_recheck_spread_is_wider_than_the_cap(db: AsyncSession) -> None:
    adapter = _Broker(_UNCOVERED, wide_after=2)
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="Bid/ask spread") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=_legs(),
            contracts_per_leg=1,
        )
    text = str(raised.value)
    assert "10%" in text
    assert "The paper order filled" not in text
    assert "The short call was not submitted" not in text
    held = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    assert held == []


@pytest.mark.asyncio
async def test_user_override_fills_a_stale_quote_at_the_latest_limit(db: AsyncSession) -> None:
    adapter = _Broker(_UNCOVERED, fresh_reads=0)
    user = _user()
    db.add(user)
    await db.commit()
    orders = await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=_legs(),
        contracts_per_leg=1,
        checks_passed=False,
        scan_id="scan-override",
        user_override=True,
        override_reasons=["Quote not current"],
    )
    assert orders[0].status == "filled"
    assert orders[0].order_type == "limit"
    assert adapter.payloads[0]["order_type"] == "limit"
    from app.services.evidence_ledger import get

    rows = [row for row in get("scan-override") if row.key == "user_override"]
    assert rows
    assert rows[-1].inputs["reasons"] == ["Quote not current"]
    assert rows[-1].inputs["user_id"] == user.id


@pytest.mark.asyncio
async def test_auto_execute_ignores_user_override(db: AsyncSession) -> None:
    adapter = _Broker(_UNCOVERED, fresh_reads=0)
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="pre-trade checks did not all pass"):
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=_legs(),
            contracts_per_leg=1,
            checks_passed=False,
            auto_execute=True,
            user_override=True,
            override_reasons=["Quote not current"],
        )


@pytest.mark.asyncio
async def test_a_single_short_is_not_paper_filled_on_an_uncovered_refusal(db: AsyncSession) -> None:
    adapter = _Broker(_UNCOVERED)
    user = _user()
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="not eligible to trade uncovered") as raised:
        await execute_strategy_legs(
            user=user,
            db=db,
            adapter=adapter,
            legs=[{"symbol": _SHORT, "side": "sell", "option_side": "call", "price": 1.10}],
            contracts_per_leg=1,
        )
    assert "The paper order filled" not in str(raised.value)
    held = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == _SHORT))
    assert held is None
