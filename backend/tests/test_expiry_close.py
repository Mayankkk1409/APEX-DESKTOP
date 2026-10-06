"""Expiry window, paper auto-close, and read-only skip."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.trading import Order, Position
from app.models.user import User
from app.schemas.market import Quote
from app.services.expiry_close import (
    close_expiring_paper_positions,
    expiring_notices,
    ny_today,
    within_alert_window,
)
from app.services.occ_symbol import parse_occ_expiry

NY = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 2)  # Friday
QUOTE_PX = 2.4


def _at(hour: int, minute: int, day: date = TODAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)


def _occ(expiry: date, root: str = "AAPL") -> str:
    return f"{root}{expiry.year % 100:02d}{expiry.month:02d}{expiry.day:02d}C00150000"


class StubAdapter:
    def __init__(self, *, price: float = QUOTE_PX, reject: bool = False) -> None:
        self.price = price
        self.reject = reject
        self.submits: list[dict] = []
        self.quotes: list[str] = []

    async def quote(self, symbol: str) -> Quote:
        self.quotes.append(symbol)
        return Quote(
            symbol=symbol,
            name=symbol,
            price=self.price,
            source="test",
            as_of=datetime.now(ZoneInfo("UTC")).isoformat(),
        )

    async def submit_order(self, **kwargs) -> dict:
        self.submits.append(kwargs)
        if self.reject:
            raise RuntimeError("broker rejected")
        return {"status": "filled", "filled_avg_price": self.price}


def _user(mode: str = "paper_funded", cash: float = 10_000.0) -> User:
    uid = str(uuid4())
    return User(
        id=uid,
        full_name="Trader",
        username=f"u{uid[:8]}",
        email=f"{uid[:8]}@example.com",
        password_hash="x",
        account_mode=mode,
        cash_balance=cash,
        buying_power=cash,
        portfolio_value=cash,
        starting_balance=cash,
    )


def _position(user: User, symbol: str, *, strategy: str = "Bull Call Spread", qty: float = 1) -> Position:
    return Position(
        user_id=user.id,
        symbol=symbol,
        qty=qty,
        avg_cost=1.5,
        current_price=1.5,
        asset_class="us_option",
        strategy_name=strategy,
    )


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_window_includes_today_and_excludes_eight_days() -> None:
    assert within_alert_window(TODAY, TODAY)
    assert within_alert_window(TODAY + timedelta(days=7), TODAY)
    assert not within_alert_window(TODAY + timedelta(days=8), TODAY)
    assert parse_occ_expiry(_occ(TODAY)) == TODAY
    assert parse_occ_expiry(_occ(TODAY + timedelta(days=8))) == TODAY + timedelta(days=8)

    user = _user()
    today_pos = _position(user, _occ(TODAY), qty=-1)
    later = _position(user, _occ(TODAY + timedelta(days=8), root="MSFT"), strategy="Bear Put Spread")
    listed = expiring_notices(user, [today_pos, later], TODAY)
    assert [row["symbol"] for row in listed] == [today_pos.symbol]
    assert listed[0]["days_left"] == 0
    assert listed[0]["direction"] == "short"
    assert listed[0]["right"] == "call"
    assert listed[0]["strike"] == 150


async def test_expires_today_is_included(db: AsyncSession) -> None:
    user = _user()
    pos = _position(user, _occ(TODAY))
    db.add(user)
    db.add(pos)
    await db.commit()

    morning = _at(10, 0)
    listed = expiring_notices(user, [pos], ny_today(morning))
    assert len(listed) == 1
    assert listed[0]["days_left"] == 0
    assert listed[0]["symbol"] == pos.symbol
    assert listed[0]["strategy"] == "Bull Call Spread"
    assert listed[0]["can_close"] is True
    assert listed[0]["strike"] == 150
    assert listed[0]["right"] == "call"
    assert listed[0]["direction"] == "long"

    adapter = StubAdapter()
    await close_expiring_paper_positions(db, adapter, now=morning)
    still = await db.get(Position, pos.id)
    assert still is not None
    assert adapter.submits == []

    after_cutoff = _at(16, 5)
    await close_expiring_paper_positions(db, adapter, now=after_cutoff)
    assert await db.get(Position, pos.id) is None
    assert adapter.submits == []
    await db.refresh(user)
    credit = QUOTE_PX * 100
    assert user.cash_balance == pytest.approx(10_000 + credit)
    assert user.buying_power == pytest.approx(10_000 + credit)
    assert user.portfolio_value == pytest.approx(10_000 + credit)
    orders = (await db.scalars(select_orders(user.id))).all()
    assert len(orders) == 1
    assert orders[0].fill_price == pytest.approx(QUOTE_PX)
    assert orders[0].side == "sell"


def select_orders(user_id: str):
    from sqlalchemy import select

    return select(Order).where(Order.user_id == user_id)


async def test_expires_in_eight_days_is_excluded(db: AsyncSession) -> None:
    user = _user()
    expiry = TODAY + timedelta(days=8)
    pos = _position(user, _occ(expiry), strategy="Bear Put Spread")
    db.add(user)
    db.add(pos)
    await db.commit()

    listed = expiring_notices(user, [pos], TODAY)
    assert listed == []

    adapter = StubAdapter()
    result = await close_expiring_paper_positions(db, adapter, now=_at(16, 5))
    assert result["closed"] == 0
    assert await db.get(Position, pos.id) is not None
    assert adapter.submits == []
    await db.refresh(user)
    assert user.cash_balance == pytest.approx(10_000)
    orders = (await db.scalars(select_orders(user.id))).all()
    assert orders == []


async def test_second_run_does_not_double_close(db: AsyncSession) -> None:
    user = _user()
    pos = _position(user, _occ(TODAY))
    db.add(user)
    db.add(pos)
    await db.commit()

    adapter = StubAdapter()
    when = _at(16, 5)
    first = await close_expiring_paper_positions(db, adapter, now=when)
    assert first["closed"] == 1
    await db.refresh(user)
    cash = user.cash_balance
    orders = (await db.scalars(select_orders(user.id))).all()
    assert len(orders) == 1

    second = await close_expiring_paper_positions(db, adapter, now=when)
    assert second["closed"] == 0
    await db.refresh(user)
    assert user.cash_balance == pytest.approx(cash)
    orders = (await db.scalars(select_orders(user.id))).all()
    assert len(orders) == 1
    assert adapter.submits == []


async def test_read_only_account_is_not_submitted(db: AsyncSession) -> None:
    user = _user("real_brokerage")
    pos = _position(user, _occ(TODAY))
    db.add(user)
    db.add(pos)
    await db.commit()

    listed = expiring_notices(user, [pos], TODAY)
    assert len(listed) == 1
    assert listed[0]["can_close"] is False

    adapter = StubAdapter()
    result = await close_expiring_paper_positions(db, adapter, now=_at(16, 5))
    assert result["closed"] == 0
    assert await db.get(Position, pos.id) is not None
    assert adapter.submits == []
    assert adapter.quotes == []
    orders = (await db.scalars(select_orders(user.id))).all()
    assert orders == []
    await db.refresh(user)
    assert user.cash_balance == pytest.approx(10_000)


async def test_past_expiry_closes_when_the_market_is_closed(db: AsyncSession) -> None:
    user = _user()
    friday = date(2026, 10, 2)
    pos = _position(user, _occ(friday))
    db.add(user)
    db.add(pos)
    await db.commit()

    saturday = datetime(2026, 10, 3, 11, 0, tzinfo=NY)
    adapter = StubAdapter()
    result = await close_expiring_paper_positions(db, adapter, now=saturday)
    assert result["closed"] == 1
    assert await db.get(Position, pos.id) is None
    assert adapter.submits == []
    orders = (await db.scalars(select_orders(user.id))).all()
    assert orders[0].fill_price == pytest.approx(QUOTE_PX)


async def test_broker_rejection_uses_quote_price(db: AsyncSession) -> None:
    user = _user()
    pos = _position(user, _occ(TODAY))
    db.add(user)
    db.add(pos)
    await db.commit()

    price = 3.37
    adapter = StubAdapter(price=price, reject=True)
    # Session still open, but past a test cutoff so the close is due and the broker is tried.
    await close_expiring_paper_positions(db, adapter, now=_at(15, 30), cutoff=time(15, 0))
    assert len(adapter.submits) == 1
    assert await db.get(Position, pos.id) is None
    orders = (await db.scalars(select_orders(user.id))).all()
    assert len(orders) == 1
    assert orders[0].fill_price == pytest.approx(price)
    await db.refresh(user)
    assert user.cash_balance == pytest.approx(10_000 + price * 100)
    assert user.portfolio_value == pytest.approx(user.cash_balance)
