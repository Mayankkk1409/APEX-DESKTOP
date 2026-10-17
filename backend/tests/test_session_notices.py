"""Login notices: closes today, then queue executions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.trading import Order, QueuedOrder
from app.models.user import User
from app.services.session_notices import (
    ack_closed_today_notices,
    closed_today_notices,
    session_arrival_bundle,
)

NY = ZoneInfo("America/New_York")


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


def _user() -> User:
    uid = str(uuid4())
    return User(
        id=uid,
        full_name="Trader",
        username=f"u{uid[:8]}",
        email=f"{uid[:8]}@example.com",
        password_hash="x",
        account_mode="paper_funded",
        cash_balance=10_000,
        buying_power=10_000,
        portfolio_value=10_000,
    )


async def test_closed_today_listed_then_acked(db: AsyncSession) -> None:
    user = _user()
    now = datetime.now(NY).astimezone(timezone.utc)
    closed = Order(
        user_id=user.id,
        symbol="AAPL261016C00150000",
        side="sell",
        qty=1,
        order_type="limit",
        fill_price=2.4,
        filled_qty=1,
        status="filled",
        filled_at=now,
        asset_class="us_option",
        multiplier=100,
        settlement={"basis": 1.5, "closed_qty": 1.0},
    )
    open_fill = Order(
        user_id=user.id,
        symbol="MSFT",
        side="buy",
        qty=1,
        order_type="limit",
        fill_price=400,
        filled_qty=1,
        status="filled",
        filled_at=now,
        asset_class="us_equity",
        multiplier=1,
    )
    db.add_all([user, closed, open_fill])
    await db.commit()

    rows = await closed_today_notices(db, user.id)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL261016C00150000"
    assert rows[0]["fill_price"] == pytest.approx(2.4)

    acked = await ack_closed_today_notices(db, user.id, [closed.id])
    assert acked == 1
    assert await closed_today_notices(db, user.id) == []


async def test_bundle_orders_closed_before_executed(db: AsyncSession) -> None:
    user = _user()
    now = datetime.now(NY).astimezone(timezone.utc)
    closed = Order(
        user_id=user.id,
        symbol="AAPL261016P00140000",
        side="buy",
        qty=1,
        order_type="limit",
        fill_price=0.5,
        filled_qty=1,
        status="filled",
        filled_at=now,
        asset_class="us_option",
        multiplier=100,
        settlement={"basis": 1.2, "closed_qty": -1.0},
    )
    queued = QueuedOrder(
        user_id=user.id,
        symbol="NVDA",
        side="buy",
        qty=1,
        order_type="limit",
        strategy_name="Equity",
        status="filled",
        reason="submitted",
        expires_at=now,
        payload={"execution_notice_pending": True, "execution_fill_price": 180.5, "share_only": True},
    )
    db.add_all([user, closed, queued])
    await db.commit()

    bundle = await session_arrival_bundle(db, user.id)
    assert len(bundle["closed_today"]) == 1
    assert len(bundle["executed_today"]) == 1
    assert bundle["closed_today"][0]["symbol"].startswith("AAPL")
    assert bundle["executed_today"][0]["symbol"] == "NVDA"
