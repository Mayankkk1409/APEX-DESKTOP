"""Broker acknowledgements are not fills unless an execution price is present."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.adapters.alpaca import AlpacaAdapter
from app.config import Settings
from app.database import Base
from app.models.trading import Order, Position
from app.models.user import User
from app.services.broker_execution import classify_execution
from app.services.fills import execute_market_fill
from app.services.position_basis import position_after_fill

OCC = "AAPL270115C00150000"


def test_basis_increase_partial_close_cover_and_flat() -> None:
    qty, avg = position_after_fill(1, 4.0, side="buy", fill_qty=1, fill_px=6.0)
    assert qty == 2
    assert avg == pytest.approx(5.0)

    qty, avg = position_after_fill(2, 5.0, side="sell", fill_qty=1, fill_px=9.0)
    assert qty == 1
    assert avg == pytest.approx(5.0)

    assert position_after_fill(1, 5.0, side="sell", fill_qty=1, fill_px=9.0) is None

    qty, avg = position_after_fill(-2, 5.0, side="buy", fill_qty=1, fill_px=3.9)
    assert qty == -1
    assert avg == pytest.approx(5.0)

    qty, avg = position_after_fill(-1, 4.0, side="sell", fill_qty=1, fill_px=6.0)
    assert qty == -2
    assert avg == pytest.approx(5.0)


def test_unfilled_partial_and_rejection_are_not_successful_fills() -> None:
    accepted = classify_execution({"id": "a", "status": "accepted", "venue": "live"}, requested_qty=1)
    assert accepted.outcome == "accepted"
    assert accepted.fill_price is None

    partial = classify_execution(
        {"id": "p", "status": "partially_filled", "filled_avg_price": 3.9, "filled_qty": 1, "venue": "live"},
        requested_qty=2,
    )
    assert partial.outcome == "partial"
    assert partial.fill_price == pytest.approx(3.9)

    rejected = classify_execution({"status": "rejected", "rejected": True, "reason": "no"}, requested_qty=1)
    assert rejected.outcome == "rejected"

    ambiguous = classify_execution({"status": "filled", "venue": "live"}, requested_qty=1)
    assert ambiguous.outcome == "ambiguous"


@pytest.fixture
async def book() -> AsyncIterator[tuple[AsyncSession, User]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        user = User(
            full_name="Fill",
            username="filluser",
            email="fill@example.com",
            password_hash="x",
            account_mode="paper_funded",
            cash_balance=10_000,
            buying_power=10_000,
            portfolio_value=10_000,
            starting_balance=10_000,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        yield db, user
    await engine.dispose()


def _adapter(result: dict) -> SimpleNamespace:
    now = datetime.now(timezone.utc).isoformat()

    async def quote(symbol: str) -> SimpleNamespace:
        return SimpleNamespace(
            symbol=symbol,
            price=4.0,
            bid=3.88,
            ask=4.12,
            as_of=now,
            source="opra",
            asset_class="us_option",
        )

    async def submit_order(**kwargs: object) -> dict:
        _ = kwargs
        return result

    return SimpleNamespace(quote=quote, submit_order=submit_order)


@pytest.mark.asyncio
async def test_cash_uses_the_390_fill_not_the_400_estimate(book: tuple[AsyncSession, User]) -> None:
    db, user = book
    order = await execute_market_fill(
        user=user,
        db=db,
        adapter=_adapter(
            {"id": "brk-390", "status": "filled", "filled_avg_price": 3.90, "filled_qty": 1, "venue": "live"}
        ),
        symbol=OCC,
        side="buy",
        qty=1,
        asset_class="us_option",
        submission_path="place_order",
    )
    assert order.status == "filled"
    assert order.fill_price == pytest.approx(3.90)
    assert user.cash_balance == pytest.approx(10_000 - 390)


@pytest.mark.asyncio
async def test_unfilled_ack_partial_duplicate_and_rejection(book: tuple[AsyncSession, User]) -> None:
    db, user = book
    accepted = await execute_market_fill(
        user=user,
        db=db,
        adapter=_adapter({"id": "brk-ack", "status": "accepted", "venue": "live"}),
        symbol=OCC,
        side="buy",
        qty=1,
        asset_class="us_option",
        submission_path="place_order",
    )
    assert accepted.status == "accepted"
    assert accepted.fill_price is None
    assert user.cash_balance == pytest.approx(10_000)
    assert await db.scalar(select(Position).where(Position.user_id == user.id)) is None

    partial = await execute_market_fill(
        user=user,
        db=db,
        adapter=_adapter(
            {
                "id": "brk-part",
                "status": "partially_filled",
                "filled_avg_price": 3.90,
                "filled_qty": 1,
                "venue": "live",
            }
        ),
        symbol=OCC,
        side="buy",
        qty=2,
        asset_class="us_option",
        submission_path="place_order",
    )
    assert partial.status == "partial"
    assert user.cash_balance == pytest.approx(10_000 - 390)
    pos = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == OCC))
    assert pos is not None and pos.qty == pytest.approx(1)

    again = await execute_market_fill(
        user=user,
        db=db,
        adapter=_adapter(
            {
                "id": "brk-part",
                "status": "partially_filled",
                "filled_avg_price": 3.90,
                "filled_qty": 1,
                "venue": "live",
            }
        ),
        symbol=OCC,
        side="buy",
        qty=2,
        asset_class="us_option",
        submission_path="place_order",
    )
    assert again.id == partial.id
    assert user.cash_balance == pytest.approx(10_000 - 390)
    rows = (await db.scalars(select(Order).where(Order.user_id == user.id, Order.broker_order_id == "brk-part"))).all()
    assert len(rows) == 1
    held = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == OCC))
    assert held is not None and held.qty == pytest.approx(1)

    with pytest.raises(ValueError):
        await execute_market_fill(
            user=user,
            db=db,
            adapter=_adapter({"status": "rejected", "rejected": True, "reason": "Broker rejected the order", "venue": "live"}),
            symbol=OCC,
            side="buy",
            qty=1,
            asset_class="us_option",
            submission_path="place_order",
        )
    assert user.cash_balance == pytest.approx(10_000 - 390)


@pytest.mark.asyncio
async def test_missing_credentials_are_not_a_demo_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = AlpacaAdapter(Settings(alpaca_api_key_id="", alpaca_api_secret_key="", allow_options_simulator=False))

    async def _dark(symbol: str, settings: Settings):
        _ = settings
        from app.schemas.market import Quote

        return Quote(symbol=symbol, name=symbol, price=None, source="unavailable", status="unavailable")

    # quote() imports get_live_quote lazily.
    monkeypatch.setattr("app.services.live_quotes.get_live_quote", _dark)
    quote = await adapter.quote("AAPL")
    assert quote.price is None
    assert quote.source == "unavailable"
    result = await adapter.submit_order(symbol="AAPL", qty=1, side="buy", order_type="market")
    assert result["rejected"] is True
    assert result.get("status") == "rejected"
    assert result.get("broker") != "demo_paper"
